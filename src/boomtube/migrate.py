from __future__ import annotations

import os
import shutil
from pathlib import Path

from .hashing import files_identical
from .util import MigrationStats, conflict_timestamp, unique_path


_MTIME_EPS = 1e-3


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _copy(src: Path, dst: Path) -> None:
    _ensure_parent(dst)
    shutil.copy2(src, dst)


def _list_files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    root = root.resolve(strict=False)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dp = Path(dirpath)
        # Prevent descending into symlinked directories
        dirnames[:] = [d for d in dirnames if not (dp / d).is_symlink()]
        for fn in filenames:
            p = dp / fn
            if p.is_symlink():
                continue
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            out[rel] = p
    return out


def migrate_file(a: Path, b: Path) -> MigrationStats:
    """Non-destructively reconcile files between A (project side) and B (target side)."""
    stats = MigrationStats()
    a_exists = a.exists()
    b_exists = b.exists()

    if a_exists and a.is_symlink():
        return stats
    if b_exists and b.is_symlink():
        return stats

    if a_exists and not b_exists:
        _copy(a, b)
        stats.copied_a_to_b += 1
        return stats
    if b_exists and not a_exists:
        _copy(b, a)
        stats.copied_b_to_a += 1
        return stats
    if not a_exists and not b_exists:
        return stats

    # Both exist
    if files_identical(a, b):
        stats.identical += 1
        return stats

    am = a.stat().st_mtime
    bm = b.stat().st_mtime

    if am > bm + _MTIME_EPS:
        _copy(a, b)
        stats.copied_a_to_b += 1
        return stats
    if bm > am + _MTIME_EPS:
        _copy(b, a)
        stats.copied_b_to_a += 1
        return stats

    # tie: conflict copy on B
    suffix = f".conflict-from-project-{conflict_timestamp()}"
    conflict = unique_path(b.with_name(b.name + suffix))
    _copy(a, conflict)
    stats.conflicts += 1
    return stats


def migrate_dir(a: Path, b: Path) -> MigrationStats:
    """Bidirectional merge between directories A (project) and B (target)."""
    stats = MigrationStats()
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)

    a_files = _list_files(a)
    b_files = _list_files(b)

    all_rels = set(a_files) | set(b_files)
    for rel in sorted(all_rels):
        ap = a_files.get(rel)
        bp = b_files.get(rel)

        if ap is None and bp is not None:
            dst = a / rel
            _copy(bp, dst)
            stats.copied_b_to_a += 1
            continue
        if bp is None and ap is not None:
            dst = b / rel
            _copy(ap, dst)
            stats.copied_a_to_b += 1
            continue
        if ap is None or bp is None:
            continue

        # Both files exist
        if files_identical(ap, bp):
            stats.identical += 1
            continue

        am = ap.stat().st_mtime
        bm = bp.stat().st_mtime

        if am > bm + _MTIME_EPS:
            _copy(ap, bp)
            stats.copied_a_to_b += 1
            continue
        if bm > am + _MTIME_EPS:
            _copy(bp, ap)
            stats.copied_b_to_a += 1
            continue

        # tie: conflict copy on target side (B)
        suffix = f".conflict-from-project-{conflict_timestamp()}"
        conflict = unique_path(bp.with_name(bp.name + suffix))
        _copy(ap, conflict)
        stats.conflicts += 1

    return stats
