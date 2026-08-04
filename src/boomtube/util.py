from __future__ import annotations

import os
from dataclasses import dataclass

CONFLICT_SUFFIX = ".conflict-from-project-"


def conflict_name(name: str, content_hash: str) -> str:
    """Deterministic conflict file name: ``{name}.conflict-from-project-{sha8}``.

    Named per content so re-runs are idempotent (F10); the timestamp survives
    in the file's mtime.
    """
    return f"{name}{CONFLICT_SUFFIX}{content_hash[:8]}"


def unique_path(path, *, max_tries: int = 1000):
    """If `path` is taken (including by a dangling symlink), append `-N` for a unique sibling.

    ``os.path.lexists`` is used so a dangling symlink at the candidate path
    counts as taken (F15: ``path.exists()`` follows symlinks and would miss it).
    """
    if not os.path.lexists(path):
        return path
    stem = path.name
    for i in range(1, max_tries + 1):
        candidate = path.with_name(f"{stem}-{i}")
        if not os.path.lexists(candidate):
            return candidate
    raise RuntimeError(f"Unable to find unique conflict path for {path}")


@dataclass
class MigrationStats:
    copied_a_to_b: int = 0
    conflicts: int = 0
    identical: int = 0
    dirs_created: int = 0
    symlinks_copied: int = 0
