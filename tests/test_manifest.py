from __future__ import annotations

import os
from pathlib import Path

import pytest

from boomtube.fsops import sniff_type
from boomtube.manifest import Entry, Manifest, classify, entry_problem, scan_tree


def build_tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "plain.txt").write_text("x", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "nested.txt").write_text("n", encoding="utf-8")
    (root / "empty-dir").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.txt").write_text("secret", encoding="utf-8")
    (root / "dir-link").symlink_to(outside, target_is_directory=True)
    (root / "file-link").symlink_to(outside / "real.txt")
    (root / "broken-link").symlink_to(tmp_path / "ghost")
    os.mkfifo(root / "pipe")
    (root / "notes.conflict-from-project-deadbeef").write_text("u", encoding="utf-8")
    return root


def test_scan_tree_records_all_kinds(tmp_path: Path):
    root = build_tree(tmp_path)
    mf = scan_tree(root)

    kinds = {e.rel: e.kind for e in mf.entries.values()}
    assert kinds == {
        "plain.txt": "file",
        "sub": "dir",
        "sub/nested.txt": "file",
        "empty-dir": "dir",
        "dir-link": "symlink",
        "file-link": "symlink",
        "broken-link": "symlink",
        "pipe": "special",
        "notes.conflict-from-project-deadbeef": "file",
    }
    # no descent through the dir symlink
    assert "dir-link/real.txt" not in mf.entries
    # raw, un-resolved link targets
    assert mf.entries["dir-link"].link_target == str(mf.root.parent / "outside")
    assert mf.entries["file-link"].link_target == str(mf.root.parent / "outside" / "real.txt")
    # sizes only on regular files
    assert mf.entries["plain.txt"].size == 1
    assert mf.entries["sub"].size is None
    assert mf.entries["dir-link"].size is None
    # resolved root recorded
    assert mf.root == root.resolve(strict=False)


def test_scan_tree_exclude_conflicts_toggles_only_conflict_entries(tmp_path: Path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "keep.txt").write_text("x", encoding="utf-8")
    (root / "a.conflict-from-project-12345678").write_text("y", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.conflict-from-project-12345678").write_text("z", encoding="utf-8")

    with_conflicts = scan_tree(root, exclude_conflicts=False)
    assert {e.rel for e in with_conflicts.entries.values()} == {
        "keep.txt",
        "a.conflict-from-project-12345678",
        "sub",
        "sub/b.conflict-from-project-12345678",
    }
    without = scan_tree(root, exclude_conflicts=True)
    assert {e.rel for e in without.entries.values()} == {"keep.txt", "sub"}


def test_scan_tree_of_symlink_root_is_empty(tmp_path: Path):
    """F21: a symlinked root is never walked through."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "x.txt").write_text("x", encoding="utf-8")
    ln = tmp_path / "ln"
    ln.symlink_to(real, target_is_directory=True)
    mf = scan_tree(ln)
    assert mf.is_empty


def test_scan_tree_of_missing_and_file_roots_is_empty(tmp_path: Path):
    assert scan_tree(tmp_path / "nope").is_empty
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    assert scan_tree(f).is_empty


def test_scan_tree_empty_dir_root_yields_empty_manifest(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    mf = scan_tree(d)
    assert mf.is_empty
    assert mf.root == d.resolve(strict=False)


def test_entry_and_manifest_helpers():
    mf = Manifest(
        root=Path("/x"),
        entries={
            "a": Entry(rel="a", kind="file", size=1),
            "b": Entry(rel="b", kind="dir"),
            "c": Entry(rel="c", kind="symlink", link_target="/t"),
        },
    )
    assert [e.rel for e in mf.of_kind("file")] == ["a"]
    assert [e.rel for e in mf.of_kind("dir")] == ["b"]
    assert [e.rel for e in mf.of_kind("symlink")] == ["c"]
    assert mf.of_kind("special") == []
    assert not mf.is_empty
    assert Manifest(root=Path("/x"), entries={}).is_empty


def test_classify_matches_sniff_type(tmp_path: Path):
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    d = tmp_path / "d"
    d.mkdir()
    ln = tmp_path / "ln"
    ln.symlink_to(tmp_path / "ghost")
    os.mkfifo(tmp_path / "pipe")
    for p in (tmp_path / "nope", f, d, ln, tmp_path / "pipe"):
        assert classify(p) == sniff_type(p)


def test_entry_problem_catches_target_symlink_for_file_entry(tmp_path: Path):
    """F12: a target-side symlink must NOT satisfy a file entry (lstat, not is_file)."""
    real = tmp_path / "real.txt"
    real.write_text("x" * 10, encoding="utf-8")
    dst = tmp_path / "dst.txt"
    dst.symlink_to(real)
    e = Entry(rel="dst.txt", kind="file", size=10)
    assert "expected file" in entry_problem(e, dst)
    # a real file of the right size satisfies it
    plain = tmp_path / "plain.txt"
    plain.write_text("x" * 10, encoding="utf-8")
    assert entry_problem(e, plain) is None


def test_entry_problem_kind_branches(tmp_path: Path):
    """Dir/symlink entries are lstat-verified; wrong kinds and bad targets are reported."""
    d = tmp_path / "d"
    d.mkdir()
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    # a dir entry whose dst is a file
    dir_e = Entry(rel="d", kind="dir")
    assert "expected dir" in entry_problem(dir_e, f)
    # a missing dst for a dir entry
    assert "expected dir" in entry_problem(dir_e, tmp_path / "ghost")
    # a symlink entry with a mismatched raw target
    sym_e = Entry(rel="ln", kind="symlink", link_target="/somewhere/else")
    ln = tmp_path / "ln"
    ln.symlink_to(tmp_path / "other")
    assert "symlink target mismatch" in entry_problem(sym_e, ln)
    # a symlink entry satisfied by the exact same raw target
    exact = Entry(rel="ln", kind="symlink", link_target=str(tmp_path / "other"))
    assert entry_problem(exact, ln) is None
    # a symlink entry whose dst is a plain file
    assert "expected symlink" in entry_problem(sym_e, f)
    # a special entry can never be verified
    special_e = Entry(rel="pipe", kind="special")
    assert "special file cannot be verified" in entry_problem(special_e, tmp_path / "x")


@pytest.mark.skipif(os.geteuid() == 0, reason="chmod-based permission test is ineffective as root")
def test_entry_problem_reports_uninspectable_dst(tmp_path: Path):
    """An OSError while inspecting dst is reported, not swallowed."""
    locked = tmp_path / "locked"
    locked.mkdir()
    inner = locked / "inner"
    inner.mkdir()
    os.chmod(locked, 0o000)
    try:
        e = Entry(rel="inner", kind="dir")
        assert "cannot inspect" in entry_problem(e, inner)
    finally:
        os.chmod(locked, 0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="chmod-based permission test is ineffective as root")
def test_scan_tree_unreadable_root_is_empty(tmp_path: Path):
    """F11: an unreadable root mid-walk yields an empty manifest, not a crash."""
    d = tmp_path / "tree"
    d.mkdir()
    (d / "f.txt").write_text("x", encoding="utf-8")
    os.chmod(d, 0o000)
    try:
        mf = scan_tree(d)
    finally:
        os.chmod(d, 0o755)
    assert mf.is_empty


def test_uncovered_rels_reports_problems(tmp_path: Path):
    from boomtube.manifest import uncovered_rels

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x" * 10, encoding="utf-8")
    mf = scan_tree(src)
    target = tmp_path / "target"
    target.mkdir()
    (target / "a.txt").write_text("x" * 10, encoding="utf-8")
    assert uncovered_rels(mf, target) == []
    (target / "a.txt").write_text("x" * 9, encoding="utf-8")
    assert uncovered_rels(mf, target) == ["a.txt"]
