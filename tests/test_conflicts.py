from __future__ import annotations

from pathlib import Path

from boomtube.hashing import sha256
from boomtube.migrate import seed_dir
from boomtube.util import conflict_name


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_deterministic_name_is_function_of_content():
    n1 = conflict_name("f", "0123456789abcdef")
    n2 = conflict_name("f", "0123456789abcdef")
    n3 = conflict_name("f", "abcdef0123456789")
    assert n1 == n2
    assert n1 != n3
    assert n1 == "f.conflict-from-project-01234567"


def test_repro9b_conflict_spread_stable(tmp_path: Path):
    """repro9b port: re-seeding the same pair twice must not duplicate or spread conflicts."""
    link = tmp_path / "a"
    target = tmp_path / "b"
    write(link / "f", "aaa")
    write(target / "f", "bbb")
    seed_dir(link, target, force=True)
    run1 = sorted(p.name for p in target.glob("*"))
    seed_dir(link, target, force=True)
    run2 = sorted(p.name for p in target.glob("*"))
    assert run1 == run2
    assert not any("-1" in name for name in run2)
    conflicts = list(target.glob("f.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "bbb"
    assert (target / "f").read_text(encoding="utf-8") == "aaa"


def test_conflict_files_excluded_from_seeding(tmp_path: Path):
    """I10: a target holding only conflict artifacts is not treated as populated."""
    link = tmp_path / "a"
    target = tmp_path / "b"
    write(link / "real.txt", "new")
    write(target / "f.conflict-from-project-12345678", "old conflict")
    stats, _ = seed_dir(link, target)
    assert stats.copied_a_to_b == 1
    assert (target / "real.txt").read_text(encoding="utf-8") == "new"
    assert (target / "f.conflict-from-project-12345678").read_text(encoding="utf-8") == "old conflict"


def test_conflict_reuses_identical_existing_file(tmp_path: Path):
    """F10: when a conflict file with identical content already exists, it is reused, not duplicated."""
    link = tmp_path / "a"
    target = tmp_path / "b"
    write(link / "f", "xxx")
    write(target / "f", "aaa")
    existing = target / conflict_name("f", sha256(target / "f"))
    existing.write_text("aaa", encoding="utf-8")

    seed_dir(link, target, force=True)
    assert (target / "f").read_text(encoding="utf-8") == "xxx"
    conflicts = list(target.glob("f.conflict-from-project-*"))
    assert len(conflicts) == 1  # reused, not duplicated
    assert conflicts[0].read_text(encoding="utf-8") == "aaa"


def test_different_content_produces_different_conflict_names(tmp_path: Path):
    link = tmp_path / "a"
    target = tmp_path / "b"
    write(link / "f", "v1")
    write(target / "f", "c1")
    seed_dir(link, target, force=True)
    names1 = sorted(p.name for p in target.glob("f.conflict-from-project-*"))
    assert len(names1) == 1

    # different content on both sides -> new deterministic conflict, old preserved
    write(link / "f", "v2")
    write(target / "f", "c2")
    seed_dir(link, target, force=True)
    names2 = sorted(p.name for p in target.glob("f.conflict-from-project-*"))
    assert len(names2) == 2
    assert len(set(names1) & set(names2)) == 1  # first conflict preserved
