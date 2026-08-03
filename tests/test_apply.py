from __future__ import annotations

import os
from pathlib import Path

import pytest

from boomtube.apply import (
    KindMismatchError,
    MigrateDisabledError,
    UnsupportedLinkTypeError,
    _is_root_or_ancestor,
    _same_target,
    _swap,
    _verify_snapshot_copied,
    apply_all,
)
from boomtube.migrate import CopyVerificationError
from boomtube.models import LinkSpec


def ctx_for(project_root: Path) -> dict[str, str]:
    return {"project_root": str(project_root), "project_name": project_root.name}


def test_migrate_false_refuses_non_empty_link(tmp_path: Path):
    """F2/repro2: migrate:false + real content -> MigrateDisabledError, data intact."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "diary.txt").write_text("10 years of journals", encoding="utf-8")
    (link_dir / "sub").mkdir()
    (link_dir / "sub" / "x.txt").write_text("x", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=False)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], MigrateDisabledError)
    assert (link_dir / "diary.txt").read_text(encoding="utf-8") == "10 years of journals"
    assert (link_dir / "sub" / "x.txt").read_text(encoding="utf-8") == "x"
    assert not (project / ".notes").is_symlink()
    assert not (tmp_path / "ext" / "notes" / "diary.txt").exists()


def test_migrate_false_allows_empty_dir(tmp_path: Path):
    """I8: an empty directory at the link path is replaceable even with migrate:false."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".notes").mkdir()
    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=False)
    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".notes").is_symlink()


def test_migrate_false_force_replaces(tmp_path: Path):
    """F2 --force: replacing without migrating is an explicit override."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("KEY=val", encoding="utf-8")
    spec = LinkSpec(link=".env", target=str(tmp_path / "ext" / "env"), kind="file", migrate=False)
    result = apply_all(project, [spec], ctx_for(project), force=True)
    assert result.failed == []
    assert (project / ".env").is_symlink()


def test_kind_mismatch_file_kind_on_dir(tmp_path: Path):
    """F8/repro5: kind:file + real dir -> typed KindMismatchError, dir intact."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".cfg"
    link_dir.mkdir()
    (link_dir / "data.txt").write_text("real data in a dir", encoding="utf-8")

    spec = LinkSpec(link=".cfg", target=str(tmp_path / "ext" / "cfg"), kind="file", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], KindMismatchError)
    assert (link_dir / "data.txt").read_text(encoding="utf-8") == "real data in a dir"
    assert not (project / ".cfg").is_symlink()


def test_kind_mismatch_dir_kind_on_file(tmp_path: Path):
    """F8: kind:dir + real file -> typed KindMismatchError, file intact."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("KEY=val", encoding="utf-8")
    spec = LinkSpec(link=".env", target=str(tmp_path / "ext" / "env"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))
    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], KindMismatchError)
    assert (project / ".env").read_text(encoding="utf-8") == "KEY=val"


def test_special_file_refused(tmp_path: Path):
    """F20/repro10b: FIFO at the link path -> typed refusal, FIFO left in place."""
    project = tmp_path / "proj"
    project.mkdir()
    fifo = project / ".pipe"
    os.mkfifo(fifo)
    spec = LinkSpec(link=".pipe", target=str(tmp_path / "ext" / "pipe"), kind="auto", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))
    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], UnsupportedLinkTypeError)
    assert fifo.exists()
    assert not fifo.is_symlink()


def test_verify_failure_aborts_link_data_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F15: a truncated copy aborts the link; the link tree is never swapped."""
    import shutil

    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "big.txt").write_text("x" * 1000, encoding="utf-8")

    real_copy2 = shutil.copy2

    def truncating_copy2(src, dst, **kwargs):
        real_copy2(src, dst, **kwargs)
        Path(dst).write_bytes(Path(dst).read_bytes()[:100])

    monkeypatch.setattr(shutil, "copy2", truncating_copy2)

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], CopyVerificationError)
    # data intact: no swap, no symlink, no staging residue
    assert (link_dir / "big.txt").read_text(encoding="utf-8") == "x" * 1000
    assert not (project / ".notes").is_symlink()
    assert not list(project.glob("*.bt-staging-*"))


def test_per_link_continuation(tmp_path: Path):
    """F12/repro15: a failing link does not abort the remaining links."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".bad").write_text("x")
    specs = [
        LinkSpec(link=".bad", target=str(tmp_path / "t1"), kind="dir", migrate=True),
        LinkSpec(link=".good", target=str(tmp_path / "t2"), kind="dir", migrate=True),
    ]
    result = apply_all(project, specs, ctx_for(project))
    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], KindMismatchError)
    assert (project / ".good").is_symlink()
    assert (project / ".bad").is_file()


def test_root_rmtree_guard(tmp_path: Path):
    """F4: the removal guard refuses the project root and its ancestors."""
    root = tmp_path / "x"
    proj = root / "proj"
    proj.mkdir(parents=True)
    assert _is_root_or_ancestor(proj, proj)
    assert _is_root_or_ancestor(root, proj)  # ancestor of the project
    assert not _is_root_or_ancestor(proj / "sub", proj)  # descendant
    assert not _is_root_or_ancestor(tmp_path / "other", proj)


def test_swap_refuses_project_root(tmp_path: Path):
    """F4: _swap must never proceed on a path equal to the project root."""
    proj = tmp_path / "proj"
    proj.mkdir()
    with pytest.raises(RuntimeError):
        _swap(proj, proj, tmp_path / "target", "x")
    assert (tmp_path / "proj").is_dir()


def test_migrate_file_link_seeds_and_swaps(tmp_path: Path):
    """migrate:true with a real FILE at the link path seeds link->target and swaps."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("KEY=val", encoding="utf-8")
    target = tmp_path / "ext" / "env"
    spec = LinkSpec(link=".env", target=str(target), kind="file", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".env").is_symlink()
    assert target.read_text(encoding="utf-8") == "KEY=val"


def test_missing_file_link_creates_parent_only(tmp_path: Path):
    """A missing file-kind link creates its target's parent dir (not the file)."""
    project = tmp_path / "proj"
    project.mkdir()
    spec = LinkSpec(link=".env", target=str(tmp_path / "ext" / "dir" / "env"), kind="file", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".env").is_symlink()
    assert (tmp_path / "ext" / "dir").is_dir()
    assert not (tmp_path / "ext" / "dir" / "env").exists()  # dangling by design


def test_same_target_on_non_symlink_is_false(tmp_path: Path):
    """readlink failure on a non-symlink path yields False (no OSError escapes)."""
    plain = tmp_path / "plain"
    plain.write_text("x", encoding="utf-8")
    assert _same_target(plain, tmp_path / "t") is False


def test_verify_snapshot_fails_on_truncated_copy(tmp_path: Path):
    """I5: the verify pass rejects a size-mismatched target copy."""
    src = tmp_path / "src.txt"
    src.write_text("x" * 100, encoding="utf-8")
    dst = tmp_path / "target"
    dst.mkdir()
    (dst / "src.txt").write_text("x" * 10, encoding="utf-8")
    with pytest.raises(CopyVerificationError):
        _verify_snapshot_copied({"src.txt": src}, dst, "test")


def test_verify_snapshot_fails_on_missing_copy(tmp_path: Path):
    """I5: the verify pass rejects a missing target copy."""
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "target"
    dst.mkdir()
    with pytest.raises(CopyVerificationError):
        _verify_snapshot_copied({"src.txt": src}, dst, "test")


def test_verify_snapshot_skips_vanished_sources(tmp_path: Path):
    """F11: a source that vanished between snapshot and verify is skipped, not an error."""
    src = tmp_path / "gone.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "target"
    dst.mkdir()
    # vanish the source before verifying
    src.unlink()
    _verify_snapshot_copied({"gone.txt": src}, dst, "test")  # no raise
