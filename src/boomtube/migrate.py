from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .fsops import sniff_type
from .hashing import files_identical, sha256
from .util import CONFLICT_SUFFIX, MigrationStats, conflict_name, unique_path

logger = logging.getLogger(__name__)


class MigrateCollisionError(RuntimeError):
    """Both the link and the target hold real content (D2) or a write-through was attempted."""


class CopyVerificationError(OSError):
    """A copied file failed post-copy size verification (F15)."""


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _copy(src: Path, dst: Path) -> None:
    """Copy `src` -> `dst`, verifying the destination size afterwards (F15).

    Refuses to write through a destination symlink or nest a file into an
    existing directory (F9/F21). Raises `CopyVerificationError` when the copy
    is truncated; a vanished `src` propagates `FileNotFoundError` for callers
    to skip (F11).
    """
    dst_type = sniff_type(dst)
    if dst_type == "symlink":
        raise MigrateCollisionError(f"refusing to write through destination symlink: {dst}")
    if dst_type == "dir":
        raise MigrateCollisionError(f"refusing to nest file into existing directory: {dst}")
    dst_existed = dst_type == "file"
    _ensure_parent(dst)
    shutil.copy2(src, dst)
    src_size = src.stat().st_size
    dst_size = dst.stat().st_size
    # Size-only verification: strict st_mtime equality false-positives on
    # FAT/exFAT/network filesystems; size catches truncation (F15, amended).
    if dst_size != src_size:
        if not dst_existed:
            try:
                dst.unlink()
            except FileNotFoundError:
                pass
        raise CopyVerificationError(
            f"copy verification failed: {src} ({src_size} bytes) -> {dst} ({dst_size} bytes)"
        )


def snapshot_files(root: Path) -> dict[str, Path]:
    """Map relpath -> Path for real files under `root` (no symlink traversal).

    Symlinks and special files are excluded (F21); conflict artifacts
    (``*.conflict-from-project-*``) are excluded so re-runs are idempotent
    (I10); only real regular files count as seedable content.
    """
    out: dict[str, Path] = {}
    if root.is_symlink():
        return out
    resolved = root.resolve(strict=False)
    if not resolved.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        dp = Path(dirpath)
        # Prevent descending into symlinked directories.
        dirnames[:] = [d for d in dirnames if not (dp / d).is_symlink()]
        for fn in filenames:
            if CONFLICT_SUFFIX in fn:
                continue
            p = dp / fn
            if p.is_symlink():
                continue
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            out[str(p.relative_to(resolved))] = p
    return out


def has_real_content(path: Path) -> bool:
    """True if `path` holds real (non-symlink) files; empty dirs don't count (I8)."""
    t = sniff_type(path)
    if t == "file":
        return True
    if t == "dir":
        return bool(snapshot_files(path))
    return False


def _type_map(root: Path) -> dict[str, str]:
    """Map rel -> ``file``/``dir`` for every real node under `root`.

    Symlinks and conflict artifacts are excluded (F21/I10). Used by the
    pre-seed type-collision scan (F9).
    """
    out: dict[str, str] = {}
    if root.is_symlink() or not root.is_dir():
        return out
    resolved = root.resolve(strict=False)
    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        dp = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not (dp / d).is_symlink()]
        for d in dirnames:
            if CONFLICT_SUFFIX in d:
                continue
            out[str((dp / d).relative_to(resolved))] = "dir"
        for fn in filenames:
            if CONFLICT_SUFFIX in fn:
                continue
            p = dp / fn
            if p.is_symlink():
                continue
            try:
                if p.is_file():
                    out[str(p.relative_to(resolved))] = "file"
            except OSError:
                continue
    return out


def _check_type_collisions(
    link_dir: Path, target_dir: Path, link_map: dict[str, str], target_map: dict[str, str]
) -> None:
    """Refuse when the same rel is a dir on one side and a file on the other (F9).

    Runs before any copy or sweep so a collision leaves zero partial state.
    """
    for rel in sorted(set(link_map) & set(target_map)):
        link_type = link_map[rel]
        target_type = target_map[rel]
        if link_type != target_type:
            raise MigrateCollisionError(
                f"type collision between link ({link_dir}) and target ({target_dir}) at '{rel}': "
                f"link has a {link_type}, target has a {target_type}"
            )


def _move_aside_conflict(path: Path) -> bool:
    """Move `path` aside as a deterministic ``{name}.conflict-from-project-{sha8}`` file.

    Returns True when a conflict file was created/kept (I10). If a conflict file
    with identical content already exists, the original is dropped (idempotent);
    a same-name different-content conflict is deduped with a numeric suffix.
    """
    try:
        content_hash = sha256(path)
    except FileNotFoundError:
        logger.debug("skipping vanished file %s", path)
        return False
    conflict = path.with_name(conflict_name(path.name, content_hash))
    if conflict.exists():
        if files_identical(conflict, path):
            path.unlink()
            return True
        conflict = unique_path(conflict)
    os.replace(path, conflict)
    return True


def seed_file(link: Path, target: Path, *, force: bool = False) -> MigrationStats:
    """Seed a single file link -> target (D1: link to target only, never reversed).

    Refuses when both sides hold real content (D2) unless `--force`, which
    moves the target aside as a deterministic conflict file before seeding.
    """
    stats = MigrationStats()
    link_type = sniff_type(link)
    target_type = sniff_type(target)

    if link_type in ("missing", "symlink"):
        return stats  # nothing to seed; never write through a link-side symlink (F21)
    if link_type == "special":
        raise MigrateCollisionError(f"cannot seed special file {link} (type {link_type})")
    if link_type != "file":
        raise MigrateCollisionError(f"cannot seed non-file link content from {link} (type {link_type})")

    if target_type == "symlink":
        raise MigrateCollisionError(f"refusing to write through destination symlink: {target}")
    if target_type == "file":
        if not force:
            raise MigrateCollisionError(
                f"both link ({link}) and target ({target}) hold content; "
                "pass --force to move the target aside as a conflict file"
            )
        if files_identical(link, target):
            stats.identical += 1
            return stats
        if sniff_type(link) != "file":
            return stats  # link vanished or changed (F11): don't churn the target
        if _move_aside_conflict(target):
            stats.conflicts += 1
    elif target_type not in ("missing",):
        raise MigrateCollisionError(f"target {target} is a {target_type}; refusing to seed into it")

    try:
        _copy(link, target)
        stats.copied_a_to_b += 1
    except FileNotFoundError:
        logger.debug("skipping vanished file %s", link)
    return stats


def seed_dir(link_dir: Path, target_dir: Path, *, force: bool = False) -> MigrationStats:
    """Seed link_dir -> target_dir (D1: one direction only).

    Refuses when both roots hold real content (D2) unless `--force`, which
    moves every target-side file aside as deterministic conflict files before
    seeding from the link side.
    """
    stats = MigrationStats()
    link_type = sniff_type(link_dir)
    target_type = sniff_type(target_dir)

    if link_type in ("missing", "symlink"):
        return stats
    if link_type != "dir":
        raise MigrateCollisionError(f"cannot seed non-directory link content from {link_dir} (type {link_type})")

    if target_type == "symlink":
        raise MigrateCollisionError(f"refusing to write through destination symlink: {target_dir}")
    if target_type == "file":
        raise MigrateCollisionError(
            f"target {target_dir} is a file but link {link_dir} is a directory; type mismatch"
        )

    link_snap = snapshot_files(link_dir)
    target_snap = snapshot_files(target_dir) if target_type == "dir" else {}

    # F9: detect dir-vs-file collisions before any copy or sweep (zero partial state).
    _check_type_collisions(link_dir, target_dir, _type_map(link_dir), _type_map(target_dir))

    if link_snap and target_snap:
        rels = sorted(set(link_snap) & set(target_snap))
        if not force:
            if rels:
                detail = ", ".join(rels[:5]) + ("..." if len(rels) > 5 else "")
                raise MigrateCollisionError(
                    f"both link ({link_dir}) and target ({target_dir}) hold content at: {detail}; "
                    "pass --force to move the target side aside as conflict files"
                )
            raise MigrateCollisionError(
                f"both link ({link_dir}) and target ({target_dir}) are non-empty; "
                "pass --force to move the target side aside as conflict files"
            )
        # Sweep target files that are not already identical to the link's file
        # at the same rel (identical files are already seeded; re-sweeping them
        # would create spurious conflict files on every re-run).
        for rel in sorted(target_snap):
            target_file = target_dir / rel
            counterpart = link_snap.get(rel)
            if counterpart is not None and files_identical(counterpart, target_file):
                continue
            if _move_aside_conflict(target_file):
                stats.conflicts += 1
        target_snap = {}

    target_dir.mkdir(parents=True, exist_ok=True)
    for rel in sorted(link_snap):
        src = link_snap[rel]
        dst = target_dir / rel
        try:
            if dst.is_file() and files_identical(src, dst):
                stats.identical += 1
                continue
            _copy(src, dst)
            stats.copied_a_to_b += 1
        except FileNotFoundError:
            logger.debug("skipping vanished file %s", src)
    return stats
