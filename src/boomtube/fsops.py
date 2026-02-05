from __future__ import annotations

import shutil
from pathlib import Path


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
