from __future__ import annotations

import os
from pathlib import Path

from boomtube.apply import apply_all
from boomtube.migrate import MigrateCollisionError
from boomtube.models import LinkSpec


def test_create_symlink_when_missing(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    target = tmp_path / "ext" / "notes"
    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
    ctx = {"project_root": str(project), "project_name": project.name}

    apply_all(project, [spec], ctx)

    link_path = project / ".notes"
    assert link_path.is_symlink()
    assert link_path.resolve(strict=False) == target.resolve(strict=False)
    assert target.is_dir()


def test_idempotent_correct_symlink(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    target = tmp_path / "ext" / "notes"
    spec = LinkSpec(link=".notes", target=str(target), kind="dir")
    ctx = {"project_root": str(project), "project_name": project.name}

    apply_all(project, [spec], ctx)
    st1 = os.lstat(project / ".notes")
    apply_all(project, [spec], ctx)
    st2 = os.lstat(project / ".notes")

    # same inode means link unchanged
    assert st1.st_ino == st2.st_ino


def test_replace_wrong_symlink(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    wrong = tmp_path / "ext" / "wrong"
    right = tmp_path / "ext" / "right"
    wrong.mkdir(parents=True)
    right.mkdir(parents=True)

    link = project / ".notes"
    link.symlink_to(wrong)

    spec = LinkSpec(link=".notes", target=str(right), kind="dir")
    ctx = {"project_root": str(project), "project_name": project.name}

    apply_all(project, [spec], ctx)
    assert link.is_symlink()
    assert link.resolve(strict=False) == right.resolve(strict=False)


def test_target_is_never_deleted_on_replace(tmp_path: Path):
    """D2: real content on both sides is a refusal; nothing is deleted or changed."""
    project = tmp_path / "proj"
    project.mkdir()
    target = tmp_path / "ext" / "notes"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("hi", encoding="utf-8")

    # Create a real directory at link path to trigger migration+replace
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a.txt").write_text("a", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
    ctx = {"project_root": str(project), "project_name": project.name}

    result = apply_all(project, [spec], ctx)

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], MigrateCollisionError)
    # nothing mutated: link tree and target both intact, no symlink created
    assert (link_dir / "a.txt").read_text(encoding="utf-8") == "a"
    assert (target / "keep.txt").read_text(encoding="utf-8") == "hi"
    assert not (project / ".notes").is_symlink()


def test_both_populated_force_preserves_target_as_conflict(tmp_path: Path):
    """D2 --force: target content is preserved as a conflict file, then link seeds."""
    project = tmp_path / "proj"
    project.mkdir()
    target = tmp_path / "ext" / "notes"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("hi", encoding="utf-8")

    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a.txt").write_text("a", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
    ctx = {"project_root": str(project), "project_name": project.name}

    result = apply_all(project, [spec], ctx, force=True)

    assert result.failed == []
    assert (project / ".notes").is_symlink()
    # link content is authoritative at the target; old target content preserved
    assert (target / "a.txt").read_text(encoding="utf-8") == "a"
    conflicts = list(target.glob("keep.txt.conflict-from-project-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "hi"
    assert (project / ".notes" / "a.txt").read_text(encoding="utf-8") == "a"
