from __future__ import annotations

import hashlib
from pathlib import Path


def sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def files_identical(a: Path, b: Path) -> bool:
    """Return True if files have identical content.

    TOCTOU-tolerant: any file vanishing between stat and read yields False
    rather than an unhandled FileNotFoundError (F11).
    """
    try:
        return _files_identical(a, b)
    except FileNotFoundError:
        return False


def _files_identical(a: Path, b: Path) -> bool:
    sa = a.stat()
    sb = b.stat()
    if sa.st_size != sb.st_size:
        return False
    return sha256(a) == sha256(b)
