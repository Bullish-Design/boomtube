from __future__ import annotations

import os
from pathlib import Path

import pytest

import boomtube.fsops as fsops
from boomtube.apply import apply_all
from boomtube.models import LinkSpec


def ctx_for(project_root: Path) -> dict[str, str]:
    return {"project_root": str(project_root), "project_name": project_root.name}


def test_sniff_type_classifications(tmp_path: Path):
    assert fsops.sniff_type(tmp_path / "missing") == "missing"
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    assert fsops.sniff_type(f) == "file"
    d = tmp_path / "d"
    d.mkdir()
    assert fsops.sniff_type(d) == "dir"
    ln = tmp_path / "ln"
    ln.symlink_to(tmp_path / "ghost")
    assert fsops.sniff_type(ln) == "symlink"  # broken symlink still 'symlink'
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert fsops.sniff_type(fifo) == "special"


def test_atomic_symlink_creates_and_replaces(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    fsops.atomic_symlink(link, target)
    assert link.is_symlink()
    assert link.resolve(strict=False) == target.resolve(strict=False)

    other = tmp_path / "other"
    other.mkdir()
    fsops.atomic_symlink(link, other)
    assert link.resolve(strict=False) == other.resolve(strict=False)
    # no temp-symlink residue after either operation
    assert not list(tmp_path.glob("*.bt-tmp-*"))


def test_rename_aside_moves_path(tmp_path: Path):
    p = tmp_path / "data"
    p.mkdir()
    (p / "x.txt").write_text("x", encoding="utf-8")
    staging = fsops.rename_aside(p)
    assert not p.exists()
    assert (staging / "x.txt").read_text(encoding="utf-8") == "x"
    assert staging.name.startswith("data.bt-staging-")


def test_reclaim_staging_residue_removes_verified_tree(tmp_path: Path):
    """F3: residue whose contents are provably in the target is removed."""
    stale = tmp_path / "data.bt-staging-999"
    stale.mkdir()
    (stale / "x.txt").write_text("old", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "x.txt").write_text("old", encoding="utf-8")
    fsops.reclaim_staging_residue(tmp_path / "data", verified_against=target)
    assert not stale.exists()


def test_reclaim_staging_residue_quarantines_unverified_tree(tmp_path: Path):
    """F3: residue with content NOT in the target is quarantined as .bt-orphan and survives."""
    stale = tmp_path / "data.bt-staging-999"
    stale.mkdir()
    (stale / "x.txt").write_text("old", encoding="utf-8")
    (stale / "only-copy.txt").write_text("unique data", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "x.txt").write_text("old", encoding="utf-8")

    fsops.reclaim_staging_residue(tmp_path / "data", verified_against=target)
    orphans = list(tmp_path.glob("data.bt-orphan*"))
    assert len(orphans) == 1
    assert (orphans[0] / "only-copy.txt").read_text(encoding="utf-8") == "unique data"
    assert (orphans[0] / "x.txt").read_text(encoding="utf-8") == "old"
    assert not stale.exists()

    # an orphan survives a second reclaim call
    fsops.reclaim_staging_residue(tmp_path / "data", verified_against=target)
    assert (orphans[0] / "only-copy.txt").read_text(encoding="utf-8") == "unique data"


def test_reclaim_never_matches_orphans(tmp_path: Path):
    """F3: .bt-orphan-* is deliberately not matched by the reclaim globs."""
    orphan = tmp_path / "data.bt-orphan-1"
    orphan.mkdir()
    (orphan / "x.txt").write_text("x", encoding="utf-8")
    fsops.reclaim_staging_residue(tmp_path / "data", verified_against=tmp_path / "target")
    assert orphan.exists()


def test_reclaim_removes_file_and_symlink_residue(tmp_path: Path):
    """File/symlink residue is always redundant and removed (D5)."""
    f = tmp_path / "data.bt-staging-999"
    f.write_text("x", encoding="utf-8")
    ln = tmp_path / "data.bt-tmp-999"
    ln.symlink_to(tmp_path / "ghost")
    fsops.reclaim_staging_residue(tmp_path / "data")
    assert not f.exists()
    assert not ln.exists()


def test_reclaim_verified_tree_remove_failure_is_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A failing remove of a verified tree is logged, never raised."""
    stale = tmp_path / "data.bt-staging-999"
    stale.mkdir()
    (stale / "x.txt").write_text("x", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")

    def boom(path):
        raise OSError("nope")

    monkeypatch.setattr(fsops, "remove_path", boom)
    fsops.reclaim_staging_residue(tmp_path / "data", verified_against=target)
    assert stale.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="chmod-based permission test is ineffective as root")
def test_reclaim_quarantine_failure_is_logged(tmp_path: Path):
    """A failing quarantine (os.replace) is logged, never raised."""
    stale = tmp_path / "data.bt-staging-999"
    stale.mkdir()
    (stale / "x.txt").write_text("x", encoding="utf-8")
    os.chmod(tmp_path, 0o500)  # not writable -> os.replace fails
    try:
        fsops.reclaim_staging_residue(tmp_path / "data")  # must not raise
    finally:
        os.chmod(tmp_path, 0o700)
    assert stale.exists()


def test_reclaim_staging_residue_survives_remove_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A failing remove during reclaim is logged, never raised."""
    stale = tmp_path / "data.bt-staging-999"
    stale.write_text("x", encoding="utf-8")  # a file residue goes through remove_path

    def boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(fsops, "remove_path", boom)
    fsops.reclaim_staging_residue(tmp_path / "data")  # must not raise
    assert stale.exists()


def test_readlink_abs_resolves_relative_target(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "ln"
    link.symlink_to("real")  # relative symlink target
    assert fsops.readlink_abs(link) == real.resolve(strict=False)


def test_remove_path_handles_special_files(tmp_path: Path):
    import os

    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    fsops.remove_path(fifo)
    assert not fifo.exists()


def test_crash_after_rename_leaves_staging_and_reruns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """I6 crash window: symlink install fails -> staging residue, data intact, rerunable."""
    import boomtube.apply as apply_mod

    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "idea.txt").write_text("precious", encoding="utf-8")
    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    ctx = ctx_for(project)

    def boom(link, target):
        raise OSError("simulated crash")

    monkeypatch.setattr(apply_mod, "atomic_symlink", boom)
    result = apply_all(project, [spec], ctx)
    assert len(result.failed) == 1
    # old tree preserved at the staging path; link path missing
    staging = list(project.glob(".notes.bt-staging-*"))
    assert len(staging) == 1
    assert (staging[0] / "idea.txt").read_text(encoding="utf-8") == "precious"
    assert not (project / ".notes").exists()
    assert not (project / ".notes").is_symlink()

    # rerun succeeds: staging reclaimed, symlink installed, data in target
    monkeypatch.undo()
    result2 = apply_all(project, [spec], ctx)
    assert result2.failed == []
    assert (project / ".notes").is_symlink()
    assert (tmp_path / "ext" / "notes" / "idea.txt").read_text(encoding="utf-8") == "precious"
    assert not list(project.glob("*.bt-staging-*"))


def test_crash_after_symlink_install_leaves_clean_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """I6 crash window: staging deletion fails -> link correct, data in target, rerun clean."""
    import boomtube.apply as apply_mod

    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "idea.txt").write_text("precious", encoding="utf-8")
    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    ctx = ctx_for(project)

    real_remove = apply_mod.remove_path

    def failing_remove(path):
        if path.name.startswith(".notes.bt-staging-"):
            raise OSError("simulated crash")
        return real_remove(path)

    monkeypatch.setattr(apply_mod, "remove_path", failing_remove)
    result = apply_all(project, [spec], ctx)
    assert len(result.failed) == 1
    # the link is already correct; the old tree survives in staging
    assert (project / ".notes").is_symlink()
    assert (project / ".notes").resolve(strict=False) == (tmp_path / "ext" / "notes").resolve(strict=False)
    staging = list(project.glob(".notes.bt-staging-*"))
    assert len(staging) == 1
    assert (staging[0] / "idea.txt").read_text(encoding="utf-8") == "precious"

    # rerun: link already correct; stale staging reclaimed
    monkeypatch.undo()
    result2 = apply_all(project, [spec], ctx)
    assert result2.failed == []
    assert not list(project.glob("*.bt-staging-*"))
