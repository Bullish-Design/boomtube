from __future__ import annotations

import logging
import os
import shutil
import stat
from pathlib import Path

from .util import unique_path

logger = logging.getLogger(__name__)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


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
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "special"


def reclaim_staging_residue(path: Path) -> None:
    """Remove stale ``<name>.bt-staging-*`` / ``<name>.bt-tmp-*`` crash residue.

    Safe: the atomic swap only renames the link tree aside after every file in
    the pre-seed snapshot has a size-verified copy in the target, so a stale
    staging tree is always redundant (its content already lives in the target).
    """
    for pattern in (f"{path.name}.bt-staging-*", f"{path.name}.bt-tmp-*"):
        for stale in path.parent.glob(pattern):
            try:
                remove_path(stale)
                logger.debug("reclaimed stale staging residue: %s", stale)
            except OSError as e:
                logger.warning("failed to reclaim stale staging residue %s: %s", stale, e)


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
        except FileNotFoundError:
            pass


def rename_aside(path: Path) -> Path:
    """Atomically move `path` aside to ``<name>.bt-staging-<pid>``; return staging path.

    Same-filesystem ``os.replace`` move; the old tree survives any crash point
    and is deleted by the caller only after the new symlink exists (I6).
    """
    reclaim_staging_residue(path)
    staging = unique_path(path.with_name(f"{path.name}.bt-staging-{os.getpid()}"))
    os.replace(path, staging)
    return staging


def symlink_to(link: Path, target: Path) -> None:
    ensure_parent_dir(link)
    link.symlink_to(target)


def remove_path(path: Path) -> None:
    """Remove a file/dir/symlink at `path` without following inner symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    # For other special cases, attempt unlink.
    path.unlink(missing_ok=True)
