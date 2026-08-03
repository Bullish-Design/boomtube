from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .fsops import (
    atomic_symlink,
    ensure_parent_dir,
    normalize_path,
    readlink_abs,
    reclaim_staging_residue,
    rename_aside,
    remove_path,
    sniff_type,
)
from .migrate import (
    CopyVerificationError,
    MigrateCollisionError,
    has_real_content,
    seed_dir,
    seed_file,
    snapshot_files,
)
from .models import BoomtubeConfig, LinkSpec
from .planning import PlannedLink, build_plan, recheck_geometry

logger = logging.getLogger(__name__)


class KindMismatchError(RuntimeError):
    """Explicit `kind` contradicts the real type at the link path (F8)."""


class MigrateDisabledError(RuntimeError):
    """`migrate: false` with real content at the link path, without `--force` (F2/I8)."""


class UnsupportedLinkTypeError(RuntimeError):
    """The link path holds a special file (FIFO/socket/device) (F20)."""


def detect_kind(spec: LinkSpec, link_path: Path, target_path: Path) -> str:
    """Detect kind "file" vs "dir" using MVP rules."""
    if spec.kind in {"file", "dir"}:
        return spec.kind

    if link_path.exists():
        return "dir" if link_path.is_dir() else "file"
    if target_path.exists():
        return "dir" if target_path.is_dir() else "file"

    # Fallback heuristic: dot-folder with no suffix -> dir, else file
    p = Path(spec.link)
    if spec.link.startswith(".") and p.suffix == "":
        return "dir"
    return "file"


def _same_target(link_path: Path, target_path: Path) -> bool:
    try:
        current = readlink_abs(link_path)
    except OSError:
        return False

    desired = normalize_path(target_path)
    return current == desired


def _is_root_or_ancestor(path: Path, project_root: Path) -> bool:
    """True if `path` is the project root or one of its ancestors (F4 guard)."""
    try:
        resolved = path.resolve(strict=False)
        root = project_root.resolve(strict=False)
    except OSError:
        return True  # refuse on resolution failure
    return root == resolved or root.is_relative_to(resolved)


def _ensure_target(kind: str, target_path: Path) -> None:
    if kind == "dir":
        target_path.mkdir(parents=True, exist_ok=True)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)


def _verify_snapshot_copied(link_snap: dict[str, Path], target_dir: Path, display: str) -> None:
    """I5: every still-existing pre-seed link file must have a size-verified copy in target."""
    for rel in sorted(link_snap):
        src = link_snap[rel]
        try:
            src.stat()
        except FileNotFoundError:
            continue  # vanished mid-run (F11): nothing left to preserve
        dst = target_dir / rel
        try:
            if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
                raise CopyVerificationError(
                    f"verify failed for '{display}': no size-verified copy of {src} at {dst}"
                )
        except FileNotFoundError:
            raise CopyVerificationError(
                f"verify failed for '{display}': missing copy of {src} at {dst}"
            ) from None


def _swap(project_root: Path, link_path: Path, target_path: Path, display: str) -> None:
    """I6 atomic swap: rename the old path aside, install the symlink, delete the old tree."""
    if _is_root_or_ancestor(link_path, project_root):
        raise RuntimeError(f"refusing to replace project root/ancestor at {link_path}")
    reclaim_staging_residue(link_path)
    staging = rename_aside(link_path)
    try:
        atomic_symlink(link_path, target_path)
    except Exception:
        logger.error(
            "atomic symlink install failed for '%s'; old content preserved at %s", display, staging
        )
        raise
    remove_path(staging)
    logger.info("replaced with symlink: %s -> %s", link_path, target_path)


def apply_link(project_root: Path, pl: PlannedLink, *, force: bool = False) -> None:
    """Apply a single planned link through the validate -> seed -> verify -> swap pipeline."""
    spec = pl.spec
    link_path = pl.link_path
    target_path = pl.target_path
    display = spec.name or spec.link
    raw_link = project_root / spec.link

    # I2: geometry re-verified against the live filesystem (parents may have
    # become symlinks through earlier links in the same run), both before and
    # after parent creation.
    recheck_geometry(project_root, raw_link, target_path, display)
    ensure_parent_dir(link_path)
    recheck_geometry(project_root, raw_link, target_path, display)

    reclaim_staging_residue(link_path)

    link_type = sniff_type(link_path)

    if link_type == "missing":
        kind = detect_kind(spec, link_path, target_path)
        _ensure_target(kind, target_path)
        atomic_symlink(link_path, target_path)
        logger.info("created symlink: %s -> %s", link_path, target_path)
        return

    if link_type == "symlink":
        if _same_target(link_path, target_path):
            logger.info("ok (already correct): %s", display)
        else:
            atomic_symlink(link_path, target_path)
            logger.info("replaced symlink: %s -> %s", link_path, target_path)
        return

    if link_type == "special":
        raise UnsupportedLinkTypeError(
            f"link '{display}' at {link_path} is a special file (FIFO/socket/device); refusing to migrate it"
        )

    # Real file/dir at the link path.
    if spec.kind in {"file", "dir"}:
        if (spec.kind == "file") != (link_type == "file"):
            raise KindMismatchError(
                f"kind '{spec.kind}' does not match the real type '{link_type}' at {link_path}"
            )

    if not spec.migrate:
        if has_real_content(link_path) and not force:
            raise MigrateDisabledError(
                f"migrate is false but '{display}' holds real content at {link_path}; "
                "pass --force to replace it without migrating"
            )
        _ensure_target("dir" if link_type == "dir" else "file", target_path)
        _swap(project_root, link_path, target_path, display)
        return

    # migrate: true — one-directional seed (D1) with both-populated refusal (D2).
    target_type = sniff_type(target_path)
    if target_type == "symlink":
        raise MigrateCollisionError(f"target {target_path} is a symlink; refusing to write through it")

    if link_type == "file":
        stats = seed_file(link_path, target_path, force=force)
    else:
        link_snap = snapshot_files(link_path)
        stats = seed_dir(link_path, target_path, force=force)
        _verify_snapshot_copied(link_snap, target_path, display)

    if stats.conflicts:
        logger.warning("migration conflicts for %s: %d conflict file(s)", display, stats.conflicts)
    logger.info("migrated %s (link->target: %d)", display, stats.copied_a_to_b)

    _swap(project_root, link_path, target_path, display)


@dataclass
class RunResult:
    """Per-link outcome of an apply run."""

    applied: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, Exception]] = field(default_factory=list)


def apply_all(project_root: Path, specs: list[LinkSpec], ctx: dict[str, str], *, force: bool = False) -> RunResult:
    """Build the validated plan for `specs`, then apply it.

    All preflight validation (geometry, templates) happens here, before any
    filesystem mutation; failures raise (PlanError / VarResolutionError).
    """
    cfg = BoomtubeConfig(version=1, vars={}, links=specs)
    planned = build_plan(project_root, cfg, ctx)
    return apply_plan(project_root, planned, force=force)


def apply_plan(project_root: Path, planned: Sequence[PlannedLink], *, force: bool = False) -> RunResult:
    """Apply a validated plan, one link at a time, isolating per-link failures.

    A failing link is recorded in `RunResult.failed` and the remaining links
    are still applied (per-link isolation, F12).
    """
    result = RunResult()
    for pl in planned:
        display = pl.spec.name or pl.spec.link
        try:
            apply_link(project_root, pl, force=force)
            result.applied.append(pl.link_path)
        except Exception as e:
            result.failed.append((pl.link_path, e))
            logger.error("failed to apply link '%s': %s", display, e)
    return result
