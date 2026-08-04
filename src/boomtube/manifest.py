from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .util import CONFLICT_SUFFIX

EntryKind = Literal["file", "dir", "symlink", "special"]


@dataclass(frozen=True)
class Entry:
    """One node of a scanned tree."""

    rel: str
    kind: EntryKind
    size: int | None = None  # regular files only
    link_target: str | None = None  # symlinks only — RAW, un-resolved


@dataclass(frozen=True)
class Manifest:
    """Full inventory of a tree, keyed by relpath (no lossy exclusions)."""

    root: Path  # the *resolved* root the rels are relative to
    entries: dict[str, Entry]

    def of_kind(self, kind: EntryKind) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind == kind]

    @property
    def is_empty(self) -> bool:
        return not self.entries


def classify(path: Path) -> str:
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


def scan_tree(root: Path, *, exclude_conflicts: bool = False) -> Manifest:
    """Full inventory of `root`. Symlinks are RECORDED but never followed.

    - A symlinked (or non-directory, or missing) root yields an empty manifest
      (F21 guarantee: a symlinked root is never walked through).
    - ``os.walk`` splits symlinks across both lists: a symlink-to-directory
      appears in `dirnames`, a symlink-to-file and broken symlinks in
      `filenames`. Both are recorded as ``symlink`` entries without descending.
    - Empty directories are recorded (``snapshot_files`` never did).
    - ``exclude_conflicts`` drops ``*.conflict-from-project-*`` entries. It is
      target-side only: a user's own conflict-named file under the link path is
      real data and must be recorded (F1).
    - TOCTOU: any vanished node is skipped (F11).
    """
    resolved = root.resolve(strict=False)
    if classify(root) != "dir":
        return Manifest(root=resolved, entries={})
    entries: dict[str, Entry] = {}
    try:
        walker = os.walk(resolved, followlinks=False)
        for dirpath, dirnames, filenames in walker:
            dp = Path(dirpath)
            kept: list[str] = []
            for d in dirnames:
                if exclude_conflicts and CONFLICT_SUFFIX in d:
                    continue
                p = dp / d
                rel = str(p.relative_to(resolved))
                if p.is_symlink():
                    entry = _symlink_entry(p, rel)
                    if entry is not None:
                        entries[rel] = entry
                    continue  # never descend through a symlinked dir
                entries[rel] = Entry(rel=rel, kind="dir")
                kept.append(d)
            dirnames[:] = kept
            for fn in filenames:
                if exclude_conflicts and CONFLICT_SUFFIX in fn:
                    continue
                p = dp / fn
                rel = str(p.relative_to(resolved))
                try:
                    st = p.lstat()
                except (FileNotFoundError, OSError):
                    continue
                if stat.S_ISLNK(st.st_mode):
                    entry = _symlink_entry(p, rel)
                    if entry is not None:
                        entries[rel] = entry
                elif stat.S_ISREG(st.st_mode):
                    entries[rel] = Entry(rel=rel, kind="file", size=st.st_size)
                elif stat.S_ISDIR(st.st_mode):
                    entries[rel] = Entry(rel=rel, kind="dir")
                else:
                    entries[rel] = Entry(rel=rel, kind="special")
    except OSError:
        # root became unreadable/vanished mid-walk (F11)
        return Manifest(root=resolved, entries={})
    return Manifest(root=resolved, entries=entries)


def _symlink_entry(path: Path, rel: str) -> Entry | None:
    """Record a symlink with its RAW target; None if it vanished (TOCTOU)."""
    try:
        raw = os.readlink(path)
    except (FileNotFoundError, OSError):
        return None
    return Entry(rel=rel, kind="symlink", link_target=raw)


def entry_problem(e: Entry, dst: Path) -> str | None:
    """Describe why `dst` does not satisfy entry `e`, or None if it does.

    lstat-based throughout — a target-side symlink never satisfies a file or
    dir entry (F12: the old verifier's ``dst.is_file()`` followed symlinks).
    """
    try:
        t = classify(dst)
    except OSError:
        return f"cannot inspect {dst}"
    if e.kind == "file":
        if t != "file":
            return f"expected file at {dst}, found {t}"
        try:
            if dst.stat().st_size != e.size:
                return f"size mismatch at {dst}: expected {e.size} bytes, found {dst.stat().st_size}"
        except OSError:
            return f"cannot stat {dst}"
    elif e.kind == "dir":
        if t != "dir":
            return f"expected dir at {dst}, found {t}"
    elif e.kind == "symlink":
        if t != "symlink":
            return f"expected symlink at {dst}, found {t}"
        try:
            if os.readlink(dst) != e.link_target:
                return f"symlink target mismatch at {dst}"
        except OSError:
            return f"cannot readlink {dst}"
    else:
        return f"special file cannot be verified: {dst}"
    return None


def uncovered_rels(mf: Manifest, target_dir: Path) -> list[str]:
    """Rels of `mf` whose copy at `target_dir` is missing or mismatched (sorted)."""
    return [rel for rel in sorted(mf.entries) if entry_problem(mf.entries[rel], target_dir / rel) is not None]
