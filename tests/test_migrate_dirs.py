from __future__ import annotations

import os
from pathlib import Path

from boomtube.migrate import migrate_dir


def set_mtime(p: Path, t: float) -> None:
    os.utime(p, (t, t))


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_a_only_file_copied_to_b(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "only.txt", "x")
    stats = migrate_dir(a, b)
    assert (b / "only.txt").read_text(encoding="utf-8") == "x"
    assert stats.copied_a_to_b == 1


def test_b_only_file_copied_to_a(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(b / "only.txt", "x")
    stats = migrate_dir(a, b)
    assert (a / "only.txt").read_text(encoding="utf-8") == "x"
    assert stats.copied_b_to_a == 1


def test_identical_file_no_action(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "same.txt", "x")
    write(b / "same.txt", "x")
    stats = migrate_dir(a, b)
    assert stats.identical == 1


def test_newer_wins_copy_direction(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    ap = write(a / "f.txt", "new")
    bp = write(b / "f.txt", "old")
    set_mtime(ap, 2000)
    set_mtime(bp, 1000)
    stats = migrate_dir(a, b)
    assert (b / "f.txt").read_text(encoding="utf-8") == "new"
    assert stats.copied_a_to_b == 1


def test_equal_mtime_conflict_copy_on_b(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    ap = write(a / "f.txt", "aaa")
    bp = write(b / "f.txt", "bbb")
    set_mtime(ap, 1000)
    set_mtime(bp, 1000)
    stats = migrate_dir(a, b)
    assert stats.conflicts == 1
    assert (b / "f.txt").read_text(encoding="utf-8") == "bbb"
    conflicts = list((b).glob("f.txt.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "aaa"


def test_inner_symlinks_are_ignored(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    # symlinked directory inside A that should not be traversed
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside / "secret.txt", "secret")
    (a / "linkdir").symlink_to(outside, target_is_directory=True)

    stats = migrate_dir(a, b)
    # Nothing copied, because the only content is behind a symlinked dir
    assert stats.copied_a_to_b == 0
    assert not (b / "linkdir" / "secret.txt").exists()
