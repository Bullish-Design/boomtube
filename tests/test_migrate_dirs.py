from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.migrate import (
    CopyVerificationError,
    MigrateCollisionError,
    seed_dir,
    snapshot_files,
)


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_link_only_file_seeded_to_target(tmp_path: Path):
    """D1: link -> target only."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "only.txt", "x")
    stats = seed_dir(link, target)
    assert (target / "only.txt").read_text(encoding="utf-8") == "x"
    assert stats.copied_a_to_b == 1
    assert stats.copied_b_to_a == 0


def test_target_only_file_is_not_copied_back(tmp_path: Path):
    """D1: no target -> link direction."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(target / "only.txt", "x")
    stats = seed_dir(link, target)
    assert stats.copied_a_to_b == 0
    assert not (link / "only.txt").exists()
    assert (target / "only.txt").read_text(encoding="utf-8") == "x"


def test_both_non_empty_disjoint_raises_collision(tmp_path: Path):
    """D2: both roots hold real content (even disjoint) -> refusal before any copy."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "a.txt", "aaa")
    write(target / "keep.txt", "keep")
    with pytest.raises(MigrateCollisionError):
        seed_dir(link, target)
    assert not (target / "a.txt").exists()  # nothing copied
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_same_rel_on_both_sides_raises_collision(tmp_path: Path):
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "f.txt", "aaa")
    write(target / "f.txt", "bbb")
    with pytest.raises(MigrateCollisionError) as ei:
        seed_dir(link, target)
    assert "f.txt" in str(ei.value)


def test_force_sweeps_target_aside_and_seeds(tmp_path: Path):
    """D2 --force: target files become conflict files; link content is authoritative."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "a.txt", "aaa")
    write(target / "keep.txt", "keep")
    write(target / "f.txt", "old")
    write(link / "f.txt", "new")
    stats = seed_dir(link, target, force=True)
    assert stats.copied_a_to_b == 2
    assert stats.conflicts == 2
    assert (target / "a.txt").read_text(encoding="utf-8") == "aaa"
    assert (target / "f.txt").read_text(encoding="utf-8") == "new"
    conflicts = list(target.glob("*.conflict-from-project-*"))
    contents = sorted(c.read_text(encoding="utf-8") for c in conflicts)
    assert contents == ["keep", "old"]


def test_force_is_idempotent_across_runs(tmp_path: Path):
    """I10: re-seeding the same pair with --force is stable (no -1 duplicates)."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "a.txt", "aaa")
    write(target / "keep.txt", "keep")
    seed_dir(link, target, force=True)
    before = sorted(p.name for p in target.glob("*"))
    # target now has link content; simulating a re-run requires link content to
    # still be present and target to hold link content only -> no new conflicts.
    seed_dir(link, target, force=True)
    after = sorted(p.name for p in target.glob("*"))
    assert before == after
    assert not any("-1" in name for name in after)


def test_inner_symlinks_are_ignored(tmp_path: Path):
    link = tmp_path / "link"
    target = tmp_path / "target"
    link.mkdir()
    target.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside / "secret.txt", "secret")
    (link / "linkdir").symlink_to(outside, target_is_directory=True)
    write(link / "real.txt", "x")

    stats = seed_dir(link, target)
    assert stats.copied_a_to_b == 1
    assert not (target / "linkdir" / "secret.txt").exists()
    assert (target / "real.txt").read_text(encoding="utf-8") == "x"


def test_vanished_file_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F11 (repro13): a file vanishing between snapshot and copy is skipped, not a crash."""
    import boomtube.migrate as M

    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "f.txt", "AAAA")
    write(link / "g.txt", "GGGG")

    real_copy = M._copy
    vanished = False

    def sneaky(src, dst):
        nonlocal vanished
        if src.name == "f.txt" and not vanished:
            vanished = True
            src.unlink()  # TOCTOU window
        return real_copy(src, dst)

    monkeypatch.setattr(M, "_copy", sneaky)
    stats = seed_dir(link, target)
    assert stats.copied_a_to_b == 1  # only g.txt survived the copy
    assert (target / "g.txt").read_text(encoding="utf-8") == "GGGG"
    assert not (target / "f.txt").exists()


def test_truncated_copy_raises_verification_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F15: per-copy size verification catches a truncated destination."""
    import shutil

    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "big.txt", "x" * 1000)

    real_copy2 = shutil.copy2

    def truncating_copy2(src, dst, **kwargs):
        real_copy2(src, dst, **kwargs)
        Path(dst).write_bytes(Path(dst).read_bytes()[:400])

    monkeypatch.setattr(shutil, "copy2", truncating_copy2)
    with pytest.raises(CopyVerificationError):
        seed_dir(link, target)
    assert not (target / "big.txt").exists()


def test_snapshot_excludes_symlinks_and_specials(tmp_path: Path):
    import os

    link = tmp_path / "link"
    link.mkdir()
    write(link / "real.txt", "x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (link / "ln").symlink_to(outside, target_is_directory=True)
    os.mkfifo(link / "pipe")
    snap = snapshot_files(link)
    assert set(snap) == {"real.txt"}


def test_broken_symlink_at_link_root_is_skipped(tmp_path: Path):
    """F21: a symlinked link root is never seeded through."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "ghost-dir", target_is_directory=True)
    target = tmp_path / "target"
    stats = seed_dir(link, target)
    assert stats.copied_a_to_b == 0
    assert not (tmp_path / "ghost-dir").exists()
