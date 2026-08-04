from __future__ import annotations

import contextlib
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
    remove_path,
    rename_aside,
    sniff_type,
)
from .manifest import Manifest, classify, entry_problem
from .migrate import (
    CopyVerificationError,
    MigrateCollisionError,
    UnsupportedLinkTypeError,
    has_real_content,
    seed_dir,
    seed_file,
)
from .models import BoomtubeConfig, LinkSpec
from .planning import PlannedLink, build_plan, recheck_geometry

logger = logging.getLogger(__name__)


class KindMismatchError(RuntimeError):
    """Explicit `kind` contradicts the real type at the link path (F8)."""


class MigrateDisabledError(RuntimeError):
    """`migrate: false` with real content at the link path, without `--force` (F2/I8)."""


def detect_kind(spec: LinkSpec, link_path: Path, target_path: Path, *, consult_link: bool = True) -> str:
    """Detect kind "file" vs "dir" using MVP rules."""
    if spec.kind in {"file", "dir"}:
        return spec.kind

    if consult_link and link_path.exists():
        return "dir" if link_path.is_dir() else "file"
    if target_path.exists():
        return "dir" if target_path.is_dir() else "file"

    # Fallback heuristic: dot-folder with no suffix -> dir, else file. Tested
    # on the BASENAME, not the whole link string (F10: `config/.nvim` is a dir
    # just like `.nvim`).
    p = Path(spec.link)
    if p.name.startswith(".") and p.suffix == "":
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


def _verify_manifest_migrated(link_mf: Manifest, target_dir: Path, display: str) -> None:
    """Every still-existing link entry must have a verified copy in the target.

    lstat-based throughout: a target-side symlink never satisfies a file or dir
    entry (F12 — the old ``dst.is_file()`` followed symlinks). Sources that
    vanished mid-run are skipped (F11).
    """
    for rel in sorted(link_mf.entries):
        e = link_mf.entries[rel]
        src = link_mf.root / rel
        if classify(src) == "missing":
            continue  # vanished mid-run (F11): nothing left to preserve
        problem = entry_problem(e, target_dir / rel)
        if problem is not None:
            raise CopyVerificationError(f"verify failed for '{display}': {problem}")


def _swap(
    project_root: Path, link_path: Path, target_path: Path, display: str, *, verified_against: Path | None = None
) -> None:
    """I6 atomic swap: rename the old path aside, install the symlink, delete the old tree.

    `verified_against` (the target) lets residue reclamation prove a stale
    staging tree is redundant before deleting it (F3).
    """
    if _is_root_or_ancestor(link_path, project_root):
        raise RuntimeError(f"refusing to replace project root/ancestor at {link_path}")
    staging = rename_aside(link_path, verified_against=verified_against)
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

    # Crash residue is only provably redundant when a migration seeded the
    # target (F3). The `migrate: false` path never seeds, so its residue must
    # always be quarantined, never auto-deleted.
    reclaim_staging_residue(link_path, verified_against=target_path if spec.migrate else None)

    link_type = sniff_type(link_path)

    if link_type == "missing":
        kind = detect_kind(spec, link_path, target_path)
        _ensure_target(kind, target_path)
        atomic_symlink(link_path, target_path)
        logger.info("created symlink: %s -> %s", link_path, target_path)
        return

    if link_type == "symlink":
        # F4: repointing an existing symlink (e.g. editing `target:` in the
        # config) must create the new target. `consult_link=False` matters:
        # `link_path.exists()` follows the symlink, so for a dangling link it
        # returns False and for a live one it reports the *target's* type —
        # neither is what we want when deciding what to create.
        kind = detect_kind(spec, link_path, target_path, consult_link=False)
        _ensure_target(kind, target_path)
        if _same_target(link_path, target_path):
            logger.info("ok (already correct): %s", display)
            return
        previous = None
        with contextlib.suppress(OSError):
            previous = readlink_abs(link_path)
        atomic_symlink(link_path, target_path)
        logger.warning(
            "repointed '%s': %s -> %s; the previous target was left untouched and is not migrated",
            display, previous, target_path,
        )
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
        _swap(project_root, link_path, target_path, display)  # nothing was seeded -> no verified_against
        return

    # migrate: true — one-directional seed (D1) with both-populated refusal (D2).
    target_type = sniff_type(target_path)
    if target_type == "symlink":
        raise MigrateCollisionError(f"target {target_path} is a symlink; refusing to write through it")

    if link_type == "file":
        stats = seed_file(link_path, target_path, force=force)
    else:
        stats, link_mf = seed_dir(link_path, target_path, force=force)
        _verify_manifest_migrated(link_mf, target_path, display)

    if stats.conflicts:
        logger.warning("migration conflicts for %s: %d conflict file(s)", display, stats.conflicts)
    logger.info("migrated %s (link->target: %d)", display, stats.copied_a_to_b)

    _swap(project_root, link_path, target_path, display, verified_against=target_path)


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
    # F13: a dangling file symlink is legitimate (.env.local-style links the
    # user is about to populate); report it once instead of failing.
    dangling = [p for p in result.applied if p.is_symlink() and not p.exists()]
    if dangling:
        logger.warning(
            "%d symlink(s) point at paths that do not exist yet: %s",
            len(dangling),
            ", ".join(str(p) for p in dangling[:5]),
        )
    return result
