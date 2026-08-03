from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.migrate import CopyVerificationError, MigrateCollisionError, seed_file


def test_link_only_file_seeds_to_target(tmp_path: Path):
    """D1: link -> target only."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    link.write_text("hello", encoding="utf-8")
    stats = seed_file(link, target)
    assert target.read_text(encoding="utf-8") == "hello"
    assert stats.copied_a_to_b == 1
    assert stats.copied_b_to_a == 0


def test_target_only_file_is_not_copied_back(tmp_path: Path):
    """D1: there is no target -> link direction anymore."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    target.write_text("hi", encoding="utf-8")
    stats = seed_file(link, target)
    assert stats.copied_a_to_b == 0
    assert not link.exists()
    assert target.read_text(encoding="utf-8") == "hi"


def test_both_exist_raises_collision(tmp_path: Path):
    """D2: both sides hold real content -> MigrateCollisionError, nothing mutated."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    link.write_text("aaa", encoding="utf-8")
    target.write_text("bbb", encoding="utf-8")
    with pytest.raises(MigrateCollisionError):
        seed_file(link, target)
    assert link.read_text(encoding="utf-8") == "aaa"
    assert target.read_text(encoding="utf-8") == "bbb"


def test_force_moves_target_aside_and_seeds(tmp_path: Path):
    """D2 --force: target content becomes a conflict file; link content seeds."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    link.write_text("aaa", encoding="utf-8")
    target.write_text("bbb", encoding="utf-8")
    stats = seed_file(link, target, force=True)
    assert stats.copied_a_to_b == 1
    assert stats.conflicts == 1
    assert target.read_text(encoding="utf-8") == "aaa"
    conflicts = list(tmp_path.glob("b.txt.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "bbb"


def test_broken_symlink_link_is_skipped_without_write_through(tmp_path: Path):
    """F21: a (broken) symlink at the link side is never seeded through."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    ghost = tmp_path / "ghost-target"
    link.symlink_to(ghost)
    target.write_text("hello", encoding="utf-8")
    stats = seed_file(link, target)
    assert stats.copied_a_to_b == 0
    assert not ghost.exists()
    assert link.is_symlink()  # untouched
    assert target.read_text(encoding="utf-8") == "hello"


def test_target_symlink_refuses_write_through(tmp_path: Path):
    """F21: seeding into a symlink destination is refused."""
    link = tmp_path / "a.txt"
    real = tmp_path / "real.txt"
    target = tmp_path / "b.txt"
    link.write_text("aaa", encoding="utf-8")
    real.write_text("orig", encoding="utf-8")
    target.symlink_to(real)
    with pytest.raises(MigrateCollisionError):
        seed_file(link, target)
    assert real.read_text(encoding="utf-8") == "orig"


def test_missing_link_is_noop(tmp_path: Path):
    stats = seed_file(tmp_path / "nope.txt", tmp_path / "b.txt")
    assert stats.copied_a_to_b == 0


def test_truncated_copy_raises_verification_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F15: a truncated destination is detected by size verification."""
    link = tmp_path / "a.txt"
    target = tmp_path / "b.txt"
    link.write_text("x" * 1000, encoding="utf-8")

    import shutil

    real_copy2 = shutil.copy2

    def truncating_copy2(src, dst, **kwargs):
        real_copy2(src, dst, **kwargs)
        # truncate the destination to half size
        Path(dst).write_bytes(Path(dst).read_bytes()[:500])

    monkeypatch.setattr(shutil, "copy2", truncating_copy2)
    with pytest.raises(CopyVerificationError):
        seed_file(link, target)
    assert not target.exists()
