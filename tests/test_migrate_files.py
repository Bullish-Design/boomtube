from __future__ import annotations

import os
from pathlib import Path

from boomtube.migrate import migrate_file


def set_mtime(p: Path, t: float) -> None:
    os.utime(p, (t, t))


def test_file_only_on_a_copies_to_b(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello", encoding="utf-8")
    stats = migrate_file(a, b)
    assert b.read_text(encoding="utf-8") == "hello"
    assert stats.copied_a_to_b == 1


def test_file_only_on_b_copies_to_a(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    b.write_text("hi", encoding="utf-8")
    stats = migrate_file(a, b)
    assert a.read_text(encoding="utf-8") == "hi"
    assert stats.copied_b_to_a == 1


def test_file_newer_wins(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("new", encoding="utf-8")
    b.write_text("old", encoding="utf-8")
    set_mtime(a, 2000)
    set_mtime(b, 1000)
    stats = migrate_file(a, b)
    assert b.read_text(encoding="utf-8") == "new"
    assert stats.copied_a_to_b == 1


def test_file_equal_mtime_conflict_copy(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aaa", encoding="utf-8")
    b.write_text("bbb", encoding="utf-8")
    set_mtime(a, 1000)
    set_mtime(b, 1000)

    stats = migrate_file(a, b)
    assert stats.conflicts == 1
    # original b unchanged
    assert b.read_text(encoding="utf-8") == "bbb"
    conflicts = list(tmp_path.glob("b.txt.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "aaa"
