from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def conflict_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def unique_path(path, *, max_tries: int = 1000):
    """If `path` exists, append `-N` to create a unique sibling path."""
    if not path.exists():
        return path
    stem = path.name
    for i in range(1, max_tries + 1):
        candidate = path.with_name(f"{stem}-{i}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find unique conflict path for {path}")


@dataclass
class MigrationStats:
    copied_a_to_b: int = 0
    copied_b_to_a: int = 0
    conflicts: int = 0
    identical: int = 0
