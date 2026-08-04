from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256(path: Path, *, chunk_size: int = CHUNK_SIZE) -> str:
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
    """Same-size check, then a block-by-block comparison that short-circuits on
    the first differing chunk (F16: the old version hashed both files fully)."""
    sa = a.stat()
    sb = b.stat()
    if sa.st_size != sb.st_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ca = fa.read(CHUNK_SIZE)
            cb = fb.read(CHUNK_SIZE)
            if ca != cb:
                return False
            if not ca:
                return True
