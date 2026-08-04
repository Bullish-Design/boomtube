from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
from pathlib import Path

from .fsops import sniff_type
from .hashing import files_identical, sha256
from .manifest import Manifest, scan_tree
from .util import MigrationStats, conflict_name, unique_path

logger = logging.getLogger(__name__)


class MigrateCollisionError(RuntimeError):
    """Both the link and the target hold real content (D2) or a write-through was attempted."""


class UnsupportedLinkTypeError(RuntimeError):
    """The link tree holds a special file (FIFO/socket/device) that cannot be migrated (F20)."""


class CopyVerificationError(RuntimeError):
    """A copied file failed post-copy size verification (F15).

    Deliberately NOT an OSError: this is a boomtube-level refusal, not an I/O
    error, so the CLI maps it to exit 5 rather than 4 (F7).
    """


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


def has_real_content(path: Path) -> bool:
    """True if `path` holds anything at all. Only a truly empty directory is 'no content'.

    ``os.scandir`` does not follow symlinks and short-circuits on the first
    entry, so a directory holding only symlinks, only empty subdirs, or only
    conflict-named files counts as real content (F2 — the README's
    `migrate: false` guarantee requires this).
    """
    t = sniff_type(path)
    if t == "file":
        return True
    if t == "dir":
        with os.scandir(path) as it:
            return any(True for _ in it)
    return False


def _check_type_collisions(link_mf: Manifest, target_mf: Manifest) -> None:
    """Refuse when the same rel has a different kind on each side (F9).

    Runs before any copy or sweep so a collision leaves zero partial state.
    Covers ALL kinds — including target-side symlinks (F11) and empty dirs —
    so a target containing *only* symlinks now counts as populated.
    """
    for rel in sorted(set(link_mf.entries) & set(target_mf.entries)):
        a, b = link_mf.entries[rel].kind, target_mf.entries[rel].kind
        if a != b:
            raise MigrateCollisionError(
                f"type collision between link ({link_mf.root}) and target ({target_mf.root}) at '{rel}': "
                f"link has a {a}, target has a {b}"
            )


def _content_key(path: Path) -> str:
    """Content hash for conflict naming — symlinks are keyed by RAW target string (2d).

    ``sha256(path)`` would *follow* a symlink; hashing the raw readlink string
    preserves the pointer without touching what it points at.
    """
    if sniff_type(path) == "symlink":
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    return sha256(path)


def _same_entry_content(a: Path, b: Path) -> bool:
    """True if two paths hold the same content (files by hash, symlinks by raw target)."""
    ta, tb = sniff_type(a), sniff_type(b)
    if ta == "symlink" and tb == "symlink":
        try:
            return os.readlink(a) == os.readlink(b)
        except OSError:
            return False
    if ta == "file" and tb == "file":
        return files_identical(a, b)
    return False


def _move_aside_conflict(path: Path) -> bool:
    """Move `path` aside as a deterministic ``{name}.conflict-from-project-{sha8}`` file.

    Returns True when a conflict file was created/kept (I10). If a conflict file
    with identical content already exists, the original is dropped (idempotent);
    a same-name different-content conflict is deduped with a numeric suffix.
    Symlinks are keyed by their raw target string, never followed (2d).
    """
    try:
        content_hash = _content_key(path)
    except OSError:
        logger.debug("skipping vanished file %s", path)
        return False
    conflict = path.with_name(conflict_name(path.name, content_hash))
    if conflict.exists():
        if _content_key(conflict) == content_hash:
            path.unlink()
            return True
        conflict = unique_path(conflict)
    os.replace(path, conflict)
    return True


def _copy_symlink(dst: Path, raw_target: str) -> None:
    """Recreate a symlink verbatim at `dst`.

    The raw target is preserved, so relative symlinks stay relative — resolving
    them here would silently rewrite them (2c). Idempotent: a symlink already
    pointing at the same raw target is left untouched.
    """
    t = sniff_type(dst)
    if t == "symlink":
        try:
            if os.readlink(dst) == raw_target:
                return  # already correct — idempotent re-run
        except OSError:
            pass
        dst.unlink()
    elif t in ("file", "dir"):
        raise MigrateCollisionError(f"refusing to replace existing {t} with symlink: {dst}")
    _ensure_parent(dst)
    os.symlink(raw_target, dst)


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


def seed_dir(link_dir: Path, target_dir: Path, *, force: bool = False) -> tuple[MigrationStats, Manifest]:
    """Seed link_dir -> target_dir (D1: one direction only).

    Refuses when both roots hold real content (D2) unless `--force`, which
    moves every *colliding* target-side entry aside as deterministic conflict
    files before seeding from the link side (F14 decision (b): non-colliding
    target content stays in place — the merged tree is a union).

    Returns ``(stats, link_manifest)`` so the caller can re-verify the migrated
    tree without re-walking it (F16).
    """
    stats = MigrationStats()
    link_type = sniff_type(link_dir)
    target_type = sniff_type(target_dir)

    if link_type in ("missing", "symlink"):
        return stats, scan_tree(link_dir, exclude_conflicts=False)
    if link_type != "dir":
        raise MigrateCollisionError(f"cannot seed non-directory link content from {link_dir} (type {link_type})")

    if target_type == "symlink":
        raise MigrateCollisionError(f"refusing to write through destination symlink: {target_dir}")
    if target_type == "file":
        raise MigrateCollisionError(
            f"target {target_dir} is a file but link {link_dir} is a directory; type mismatch"
        )

    # Link side: exclude NOTHING — symlinks, empty dirs and conflict-named files
    # are all real data (F1). Target side: exclude conflict artifacts so re-runs
    # are idempotent (I10).
    link_mf = scan_tree(link_dir, exclude_conflicts=False)
    specials = link_mf.of_kind("special")
    if specials:
        detail = ", ".join(e.rel for e in specials[:5])
        raise UnsupportedLinkTypeError(
            f"link tree {link_dir} contains special file(s) (FIFO/socket/device) that cannot be "
            f"migrated: {detail}; move or delete them first"
        )
    target_mf = (
        scan_tree(target_dir, exclude_conflicts=True) if target_type == "dir" else Manifest(root=target_dir, entries={})
    )

    # F9/F11: type collisions over ALL kinds, before any copy or sweep.
    _check_type_collisions(link_mf, target_mf)

    if link_mf.entries and target_mf.entries:
        rels = sorted(set(link_mf.entries) & set(target_mf.entries))
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
        # --force: sweep only the colliding rels (F14 (b)). Dir/dir is a merge,
        # not a conflict; identical content is already seeded and must not be
        # re-swept (that would create spurious conflict files on every re-run).
        for rel in rels:
            link_e = link_mf.entries[rel]
            target_e = target_mf.entries[rel]
            if link_e.kind == "dir" and target_e.kind == "dir":
                continue
            target_file = target_dir / rel
            if _same_entry_content(link_dir / rel, target_file):
                continue
            if _move_aside_conflict(target_file):
                stats.conflicts += 1

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. directories, shallowest first (recreates EMPTY dirs — F1)
    for e in sorted(link_mf.of_kind("dir"), key=lambda e: (e.rel.count(os.sep), e.rel)):
        dst = target_dir / e.rel
        dst.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            shutil.copystat(link_mf.root / e.rel, dst)  # best effort: mode/mtime
        stats.dirs_created += 1

    # 2. regular files — unchanged _copy(), still size-verified
    for e in sorted(link_mf.of_kind("file"), key=lambda e: e.rel):
        src, dst = link_mf.root / e.rel, target_dir / e.rel
        try:
            if sniff_type(dst) == "file" and files_identical(src, dst):
                stats.identical += 1
                continue
            _copy(src, dst)
            stats.copied_a_to_b += 1
        except FileNotFoundError:
            logger.debug("skipping vanished file %s", src)

    # 3. symlinks last, so their parents exist
    for e in sorted(link_mf.of_kind("symlink"), key=lambda e: e.rel):
        assert e.link_target is not None
        _copy_symlink(target_dir / e.rel, e.link_target)
        stats.symlinks_copied += 1

    return stats, link_mf
