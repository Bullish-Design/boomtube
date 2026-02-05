from __future__ import annotations

import logging
from pathlib import Path

from .fsops import ensure_parent_dir, is_symlink, normalize_path, readlink_abs, remove_path, symlink_to
from .migrate import migrate_dir, migrate_file
from .models import LinkSpec

logger = logging.getLogger(__name__)


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


def apply_link(project_root: Path, spec: LinkSpec, ctx: dict[str, str]) -> None:
    link_path = project_root / spec.link
    target_rendered = spec.target.format_map(ctx)
    target_path = normalize_path(Path(target_rendered), base=project_root)

    ensure_parent_dir(link_path)

    kind = detect_kind(spec, link_path, target_path)

    # Ensure target exists appropriately
    if kind == "dir":
        target_path.mkdir(parents=True, exist_ok=True)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    display_name = spec.name or spec.link

    if not link_path.exists() and not is_symlink(link_path):
        symlink_to(link_path, target_path)
        logger.info("created symlink: %s -> %s", link_path, target_path)
        return

    if is_symlink(link_path):
        if _same_target(link_path, target_path):
            logger.info("ok (already correct): %s", display_name)
            return
        remove_path(link_path)
        symlink_to(link_path, target_path)
        logger.info("replaced symlink: %s -> %s", link_path, target_path)
        return

    # Existing real file/dir
    if spec.migrate:
        if kind == "dir":
            stats = migrate_dir(link_path, target_path)
        else:
            stats = migrate_file(link_path, target_path)
        if stats.conflicts:
            logger.warning(
                "migration conflicts for %s: %s conflict(s)", display_name, stats.conflicts
            )
        logger.info(
            "migrated %s (A->B: %d, B->A: %d, identical: %d)",
            display_name,
            stats.copied_a_to_b,
            stats.copied_b_to_a,
            stats.identical,
        )

    remove_path(link_path)
    symlink_to(link_path, target_path)
    logger.info("replaced with symlink: %s -> %s", link_path, target_path)


def apply_all(project_root: Path, specs: list[LinkSpec], ctx: dict[str, str]) -> None:
    for spec in specs:
        apply_link(project_root, spec, ctx)
