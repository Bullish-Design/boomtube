from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .fsops import normalize_path
from .models import BoomtubeConfig, LinkSpec
from .resolve import render_template


class PlanError(RuntimeError):
    """The resolved plan violates a safety invariant (maps to exit 2)."""


@dataclass(frozen=True)
class PlannedLink:
    """A fully rendered, geometry-validated link ready for apply-time checks."""

    spec: LinkSpec
    link_path: Path
    target_path: Path
    migrate: bool


def _casefold(p: Path) -> str:
    return str(p).casefold()


def _common_path(paths: Sequence[Path]) -> str | None:
    """Case-insensitive common ancestor path, or None when none exists.

    `os.path.commonpath` is case-sensitive and raises ValueError when the paths
    share no common prefix (e.g. different drives on Windows). Casefolding keeps
    the geometry invariant valid on case-insensitive filesystems (macOS/Windows
    defaults); treating the ValueError as "disjoint" handles cross-drive paths.
    """
    try:
        return os.path.commonpath([_casefold(p) for p in paths])
    except ValueError:
        return None


def _same_path(a: Path, b: Path) -> bool:
    return _casefold(a) == _casefold(b)


def _strictly_inside(inner: Path, outer: Path) -> bool:
    """True if `inner` resolves strictly inside `outer` (never equal)."""
    cp = _common_path([inner, outer])
    return cp is not None and cp == _casefold(outer) and not _same_path(inner, outer)


def build_plan(project_root: Path, cfg: BoomtubeConfig, ctx: Mapping[str, str]) -> list[PlannedLink]:
    """Render and validate the full plan before any filesystem mutation.

    Raises `PlanError` (exit 2) for geometrically unsafe configs and
    `VarResolutionError` for template failures — all before the apply flow
    touches the filesystem.
    """
    root = project_root.resolve(strict=False)
    planned: list[PlannedLink] = []
    for spec in cfg.links:
        display = spec.name or spec.link

        rendered = render_template(spec.target, ctx).strip()
        if rendered == "":
            raise PlanError(f"target for link '{display}' renders empty; target must be non-empty")

        # Resolve the link's *parent* (where the symlink will be created), then
        # append the final component. A stale symlink *at* the link path points
        # wherever it points and will be replaced (unlinked) by the apply flow,
        # so its current target must not count as an escape; a symlinked
        # *parent* directory, however, would really place the link outside the
        # project and must be rejected (F3 defense in depth).
        raw_link = root / spec.link
        link_path = raw_link.parent.resolve(strict=False) / raw_link.name
        target_path = normalize_path(Path(rendered), base=root)

        # I1 geometry invariants (F3/F4/F13/F1), enforced before any mutation.
        if _same_path(link_path, root):
            raise PlanError(f"link '{display}' resolves to the project root; link must be strictly inside the project")
        if not _strictly_inside(link_path, root):
            raise PlanError(
                f"link '{display}' resolves outside the project root ({link_path}); "
                "link must stay inside the project root"
            )
        if _same_path(target_path, root):
            raise PlanError(f"target '{spec.target}' resolves to the project root; target must not be the project root")

        cp = _common_path([link_path, target_path])
        if cp is not None and (cp == _casefold(link_path) or cp == _casefold(target_path)):
            raise PlanError(
                f"link '{display}' ({link_path}) and target '{spec.target}' ({target_path}) must not overlap; "
                "neither path may contain the other"
            )

        planned.append(PlannedLink(spec=spec, link_path=link_path, target_path=target_path, migrate=spec.migrate))
    return planned


def recheck_geometry(project_root: Path, raw_link: Path, target_path: Path, display: str) -> None:
    """Apply-time re-verification of the I1 invariants against the live filesystem.

    `raw_link` is the un-resolved ``project_root / spec.link``; parents may have
    become symlinks through earlier links in the same run, so the resolution is
    recomputed here. Any violation raises `PlanError` and leaves the link
    untouched (I2).
    """
    root = project_root.resolve(strict=False)
    resolved_link = raw_link.parent.resolve(strict=False) / raw_link.name
    if _same_path(resolved_link, root):
        raise PlanError(f"link '{display}' resolves to the project root; refusing to touch the project root")
    if not _strictly_inside(resolved_link, root):
        raise PlanError(
            f"link '{display}' resolves outside the project root ({resolved_link}); refusing to continue"
        )
    resolved_target = target_path.resolve(strict=False)
    if _same_path(resolved_target, root):
        raise PlanError(f"target for link '{display}' resolves to the project root; refusing")
    cp = _common_path([resolved_link, resolved_target])
    if cp is not None and (cp == _casefold(resolved_link) or cp == _casefold(resolved_target)):
        raise PlanError(f"link '{display}' and its target overlap; refusing to continue")
