from __future__ import annotations

import glob
import logging
import os
import shutil
from pathlib import Path

from .manifest import classify, scan_tree, uncovered_rels
from .util import unique_path

logger = logging.getLogger(__name__)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def readlink_abs(link: Path) -> Path:
    """Read a symlink and return an absolute path (best effort)."""
    raw = link.readlink()
    if not raw.is_absolute():
        raw = (link.parent / raw)
    return raw.resolve(strict=False)


def normalize_path(path: Path, *, base: Path | None = None) -> Path:
    """Normalize a path for comparison.

    - Expands `~`.
    - If relative and base is provided, resolves relative to base.
    - Resolves without requiring the path to exist.
    """
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = (base / p) if base else p
    return p.resolve(strict=False)


def sniff_type(path: Path) -> str:
    """Classify `path` via lstat: ``missing | file | dir | symlink | special``.

    A broken symlink is reported as ``symlink`` (lstat succeeds on the link
    itself). Other OSErrors (e.g. permission denied on a parent) propagate so
    they surface as per-link failures rather than being misread as ``missing``.
    """
    return classify(path)


def reclaim_staging_residue(path: Path, *, verified_against: Path | None = None) -> None:
    """Reclaim ``<name>.bt-staging-*`` / ``<name>.bt-tmp-*`` crash residue.

    A staging tree is only redundant if its contents are provably present in
    the target (`verified_against`). Anything unverifiable is quarantined as
    ``<name>.bt-orphan-*``, which is deliberately NOT matched by these globs,
    so it is never auto-deleted (F3). ``<name>`` is glob-escaped so a link
    named e.g. ``[mn]`` cannot touch a sibling's residue (F6). Never raises:
    failures are logged.
    """
    for suffix in (".bt-staging-*", ".bt-tmp-*"):
        for stale in path.parent.glob(glob.escape(path.name) + suffix):
            if stale.is_symlink() or stale.is_file():
                # Temp symlinks (atomic_symlink) are never data; a staging
                # *file* only exists after its seed+verify completed, so it is
                # always redundant (D5).
                try:
                    remove_path(stale)
                    logger.debug("reclaimed stale staging residue: %s", stale)
                except OSError as e:
                    logger.warning("failed to reclaim stale staging residue %s: %s", stale, e)
                continue
            if verified_against is not None and _tree_is_covered_by(stale, verified_against):
                try:
                    remove_path(stale)
                    logger.debug("reclaimed verified stale staging residue: %s", stale)
                except OSError as e:
                    logger.warning("failed to reclaim stale staging residue %s: %s", stale, e)
                continue
            orphan = unique_path(stale.with_name(f"{path.name}.bt-orphan"))
            try:
                os.replace(stale, orphan)
            except OSError as e:
                logger.warning("failed to quarantine stale staging residue %s: %s", stale, e)
                continue
            logger.warning(
                "preserved unverified crash residue as %s — inspect and remove manually", orphan
            )


def _tree_is_covered_by(stale: Path, target_dir: Path) -> bool:
    """True if every entry of the stale tree has a verified copy under `target_dir`.

    The stale tree is scanned fresh (lstat-based, never following symlinks); a
    tree is only redundant if nothing in it is missing from the target.
    """
    mf = scan_tree(stale, exclude_conflicts=False)
    return not uncovered_rels(mf, target_dir)


def atomic_symlink(link: Path, target: Path) -> None:
    """Atomically create or replace `link` as a symlink to `target`.

    Builds a temp symlink then ``os.replace``s it over `link`, so a stale
    symlink is replaced in a single atomic step (I6).
    """
    ensure_parent_dir(link)
    tmp = unique_path(link.with_name(f"{link.name}.bt-tmp-{os.getpid()}"))
    try:
        tmp.symlink_to(target)
        os.replace(tmp, link)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass  # a PermissionError here must not mask the real exception (F16)


def rename_aside(path: Path, *, verified_against: Path | None = None) -> Path:
    """Atomically move `path` aside to ``<name>.bt-staging-<pid>``; return staging path.

    Same-filesystem ``os.replace`` move; the old tree survives any crash point
    and is deleted by the caller only after the new symlink exists (I6). Stale
    residue is reclaimed first, verified against the target when provided.
    """
    reclaim_staging_residue(path, verified_against=verified_against)
    staging = unique_path(path.with_name(f"{path.name}.bt-staging-{os.getpid()}"))
    os.replace(path, staging)
    return staging


def remove_path(path: Path) -> None:
    """Remove a file/dir/symlink at `path` without following inner symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    # For other special cases (e.g. FIFOs/sockets), attempt unlink.
    path.unlink(missing_ok=True)
