from __future__ import annotations

from dataclasses import dataclass

CONFLICT_SUFFIX = ".conflict-from-project-"


def conflict_name(name: str, content_hash: str) -> str:
    """Deterministic conflict file name: ``{name}.conflict-from-project-{sha8}``.

    Named per content so re-runs are idempotent (F10); the timestamp survives
    in the file's mtime.
    """
    return f"{name}{CONFLICT_SUFFIX}{content_hash[:8]}"


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
