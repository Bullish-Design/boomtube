from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.migrate import (
    CopyVerificationError,
    MigrateCollisionError,
    scan_tree,
    seed_dir,
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
    stats, _ = seed_dir(link, target)
    assert (target / "only.txt").read_text(encoding="utf-8") == "x"
    assert stats.copied_a_to_b == 1


def test_target_only_file_is_not_copied_back(tmp_path: Path):
    """D1: no target -> link direction."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(target / "only.txt", "x")
    stats, _ = seed_dir(link, target)
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


def test_force_sweeps_colliding_target_aside_and_seeds(tmp_path: Path):
    """D2 --force: colliding target entries become conflict files; non-colliding stay (F14 (b))."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    write(link / "a.txt", "aaa")
    write(target / "keep.txt", "keep")
    write(target / "f.txt", "old")
    write(link / "f.txt", "new")
    stats, _ = seed_dir(link, target, force=True)
    assert stats.copied_a_to_b == 2
    assert stats.conflicts == 1  # only f.txt collides; keep.txt is left in place
    assert (target / "a.txt").read_text(encoding="utf-8") == "aaa"
    assert (target / "f.txt").read_text(encoding="utf-8") == "new"
    # non-colliding target file survives in place (union, not sweep-all)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
    conflicts = list(target.glob("f.txt.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "old"
    assert not list(target.glob("keep.txt.conflict-from-project-*"))


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


def test_inner_symlinks_are_copied_not_followed(tmp_path: Path):
    """F1: inner symlinks are recreated verbatim in the target, never followed."""
    import os

    link = tmp_path / "link"
    target = tmp_path / "target"
    link.mkdir()
    target.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside / "secret.txt", "secret")
    (link / "linkdir").symlink_to(outside, target_is_directory=True)
    write(link / "real.txt", "x")

    stats, _ = seed_dir(link, target)
    assert stats.copied_a_to_b == 1
    # copied verbatim, never followed: no descent, so no real dir under target
    assert (target / "linkdir").is_symlink()
    assert os.readlink(target / "linkdir") == str(outside)
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
    stats, _ = seed_dir(link, target)
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


def test_scan_tree_records_symlinks_and_specials(tmp_path: Path):
    import os

    link = tmp_path / "link"
    link.mkdir()
    write(link / "real.txt", "x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (link / "ln").symlink_to(outside, target_is_directory=True)
    os.mkfifo(link / "pipe")
    mf = scan_tree(link, exclude_conflicts=False)
    assert {e.rel: e.kind for e in mf.entries.values()} == {"real.txt": "file", "ln": "symlink", "pipe": "special"}


def test_broken_symlink_at_link_root_is_skipped(tmp_path: Path):
    """F21: a symlinked link root is never seeded through."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "ghost-dir", target_is_directory=True)
    target = tmp_path / "target"
    stats, _ = seed_dir(link, target)
    assert stats.copied_a_to_b == 0
    assert not (tmp_path / "ghost-dir").exists()


def test_repro7_type_collision_zero_partial_state(tmp_path: Path):
    """repro7 port: link file 'x' vs target dir 'x/' -> pre-scan error, zero partial state."""
    link = tmp_path / "a"
    target = tmp_path / "b"
    write(link / "x", "A-file-x")
    write(link / "z.txt", "after-x-in-sorted-order")
    (target / "x").mkdir(parents=True)
    write(target / "x" / "inner.txt", "B-dir-x")

    with pytest.raises(MigrateCollisionError) as ei:
        seed_dir(link, target, force=True)
    assert "x" in str(ei.value)
    # zero partial state: nothing copied, nothing swept, nothing deleted
    assert (link / "x").read_text(encoding="utf-8") == "A-file-x"
    assert (target / "x" / "inner.txt").read_text(encoding="utf-8") == "B-dir-x"
    assert not (target / "z.txt").exists()
    assert not list(target.glob("*.conflict-from-project-*"))


def test_repro7b_link_dir_vs_target_file_collision(tmp_path: Path):
    """Reverse F9 collision: link dir 'x/' vs target file 'x'."""
    link = tmp_path / "a"
    target = tmp_path / "b"
    (link / "x").mkdir(parents=True)
    write(link / "x" / "inner.txt", "L")
    write(target / "x", "T-file")
    with pytest.raises(MigrateCollisionError):
        seed_dir(link, target, force=True)


def test_copy_refuses_nesting_into_dir(tmp_path: Path):
    """F9: _copy must never silently nest a file into an existing directory."""
    import boomtube.migrate as M

    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(MigrateCollisionError):
        M._copy(src, dst)


def test_copy_refuses_write_through_symlink(tmp_path: Path):
    """F21: _copy must never write through a destination symlink."""
    import boomtube.migrate as M

    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    real = tmp_path / "real.txt"
    real.write_text("orig", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    dst.symlink_to(real)
    with pytest.raises(MigrateCollisionError):
        M._copy(src, dst)
    assert real.read_text(encoding="utf-8") == "orig"


def test_seed_dir_into_file_target_refused(tmp_path: Path):
    """F9: a directory link must not seed into a file target."""
    link = tmp_path / "link"
    link.mkdir()
    write(link / "x.txt", "x")
    target = tmp_path / "target"
    target.write_text("file", encoding="utf-8")
    with pytest.raises(MigrateCollisionError):
        seed_dir(link, target)


def test_scan_tree_of_missing_path_is_empty(tmp_path: Path):
    assert scan_tree(tmp_path / "nope").is_empty


def test_scan_tree_of_symlink_root_is_empty(tmp_path: Path):
    """F21: a symlinked root is never walked through."""
    real = tmp_path / "real"
    real.mkdir()
    write(real / "x.txt", "x")
    ln = tmp_path / "ln"
    ln.symlink_to(real, target_is_directory=True)
    assert scan_tree(ln).is_empty


def test_scan_tree_records_file_symlinks(tmp_path: Path):
    """File symlinks inside the tree are recorded as symlink entries, never followed."""
    import boomtube.migrate as M

    link = tmp_path / "link"
    link.mkdir()
    write(link / "real.txt", "x")
    real_file = tmp_path / "outside.txt"
    real_file.write_text("secret", encoding="utf-8")
    (link / "fileln").symlink_to(real_file)

    mf = M.scan_tree(link, exclude_conflicts=False)
    kinds = {e.rel: e.kind for e in mf.entries.values()}
    assert kinds == {"real.txt": "file", "fileln": "symlink"}


def test_scan_tree_link_side_includes_conflict_dirs(tmp_path: Path):
    """F1: link-side conflict-named entries are real data and are NOT excluded."""
    import boomtube.migrate as M

    link = tmp_path / "link"
    link.mkdir()
    (link / "x.conflict-from-project-12345678").mkdir()
    mf = M.scan_tree(link, exclude_conflicts=False)
    assert {e.rel: e.kind for e in mf.entries.values()} == {"x.conflict-from-project-12345678": "dir"}


def test_has_real_content_classifications(tmp_path: Path):
    import boomtube.migrate as M

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert M.has_real_content(empty_dir) is False
    filled = tmp_path / "filled"
    filled.mkdir()
    write(filled / "a.txt", "x")
    assert M.has_real_content(filled) is True
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    assert M.has_real_content(f) is True
    assert M.has_real_content(tmp_path / "missing") is False


def test_has_real_content_symlinks_subdirs_conflicts(tmp_path: Path):
    """F2: a dir of only symlinks / empty subdirs / conflict files is real content."""
    import boomtube.migrate as M

    symlinks = tmp_path / "symlinks"
    symlinks.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x").write_text("x", encoding="utf-8")
    (symlinks / "s1").symlink_to(outside / "x")
    (symlinks / "s2").symlink_to(outside / "x")
    assert M.has_real_content(symlinks) is True

    subdirs = tmp_path / "subdirs"
    subdirs.mkdir()
    (subdirs / "empty-sub").mkdir()
    assert M.has_real_content(subdirs) is True

    conflicts = tmp_path / "conflicts"
    conflicts.mkdir()
    write(conflicts / "a.conflict-from-project-12345678", "x")
    assert M.has_real_content(conflicts) is True


def test_seed_dir_file_link_refused(tmp_path: Path):
    """seed_dir only seeds directory content; a file link is refused."""
    link = tmp_path / "afile"
    link.write_text("x", encoding="utf-8")
    with pytest.raises(MigrateCollisionError):
        seed_dir(link, tmp_path / "out")


def test_seed_dir_target_symlink_refused(tmp_path: Path):
    """F21: seeding into a symlinked target directory is refused."""
    link = tmp_path / "link"
    link.mkdir()
    write(link / "x.txt", "x")
    real = tmp_path / "real"
    real.mkdir()
    target = tmp_path / "target"
    target.symlink_to(real, target_is_directory=True)
    with pytest.raises(MigrateCollisionError):
        seed_dir(link, target)
    assert not (real / "x.txt").exists()


def test_force_sweeps_target_symlink_into_conflict(tmp_path: Path):
    """2d: a colliding target symlink is swept aside keyed by its RAW target string."""
    import os

    link = tmp_path / "link"
    link.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (link / "ln").symlink_to("link-side")
    write(link / "a.txt", "x")
    (target / "ln").symlink_to("target-side")

    stats, _ = seed_dir(link, target, force=True)
    assert stats.conflicts == 1
    assert (target / "ln").is_symlink()
    assert os.readlink(target / "ln") == "link-side"
    conflicts = list(target.glob("ln.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].is_symlink()
    assert os.readlink(conflicts[0]) == "target-side"


def test_force_sweep_skips_identical_symlink(tmp_path: Path):
    """2d: a colliding symlink with the same raw target is left alone (idempotent)."""
    import os

    link = tmp_path / "link"
    link.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    write(link / "a.txt", "x")
    (link / "ln").symlink_to("shared")
    (target / "ln").symlink_to("shared")

    stats, _ = seed_dir(link, target, force=True)
    assert stats.conflicts == 0
    assert os.readlink(target / "ln") == "shared"


def test_same_entry_content_symlink_and_fallthrough(tmp_path: Path):
    """_same_entry_content: symlink-vs-symlink and mixed-type fallthrough."""
    import boomtube.migrate as M

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.symlink_to("x")
    b.symlink_to("x")
    assert M._same_entry_content(a, b) is True
    b.unlink()
    b.symlink_to("y")
    assert M._same_entry_content(a, b) is False
    c = tmp_path / "c"
    c.write_text("x", encoding="utf-8")
    assert M._same_entry_content(a, c) is False  # symlink vs file


def test_copy_symlink_idempotent_and_refusals(tmp_path: Path):
    """_copy_symlink: same target is a no-op; an existing file/dir is refused."""
    import os

    import boomtube.migrate as M

    dst = tmp_path / "dst"
    dst.symlink_to("same")
    M._copy_symlink(dst, "same")  # no-op, still a symlink to 'same'
    assert dst.is_symlink()
    assert os.readlink(dst) == "same"
    dst.unlink()
    dst.symlink_to("old")
    M._copy_symlink(dst, "new")  # replaced verbatim
    assert os.readlink(dst) == "new"

    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(MigrateCollisionError):
        M._copy_symlink(f, "any")
    d = tmp_path / "d"
    d.mkdir()
    with pytest.raises(MigrateCollisionError):
        M._copy_symlink(d, "any")


def test_seed_dir_symlink_loop_is_idempotent(tmp_path: Path):
    """Re-seeding with --force leaves an already-correct symlink untouched (inode-stable)."""
    import os

    import boomtube.migrate as M

    link = tmp_path / "link"
    target = tmp_path / "target"
    link.mkdir()
    target.mkdir()
    (link / "ln").symlink_to("x")
    write(link / "a.txt", "x")
    M.seed_dir(link, target)
    first = (target / "ln").lstat().st_ino
    M.seed_dir(link, target, force=True)
    assert (target / "ln").lstat().st_ino == first
    assert os.readlink(target / "ln") == "x"


def test_force_sweep_merges_shared_subdirs(tmp_path: Path):
    """2b: a dir present on both sides is merged, not swept as a conflict."""
    link = tmp_path / "link"
    target = tmp_path / "target"
    (link / "sub").mkdir(parents=True)
    write(link / "sub" / "f.txt", "f")
    (target / "sub").mkdir(parents=True)
    write(target / "sub" / "g.txt", "g")

    stats, _ = seed_dir(link, target, force=True)
    assert stats.conflicts == 0
    assert (target / "sub" / "f.txt").read_text(encoding="utf-8") == "f"
    assert (target / "sub" / "g.txt").read_text(encoding="utf-8") == "g"
