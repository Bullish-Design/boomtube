from __future__ import annotations

from pathlib import Path

from boomtube.apply import KindMismatchError, apply_all, detect_kind
from boomtube.fsops import sniff_type
from boomtube.models import LinkSpec


def ctx_for(project_root: Path) -> dict[str, str]:
    return {"project_root": str(project_root), "project_name": project_root.name}


def test_explicit_kind_matching_reality_applies(tmp_path: Path):
    """An explicit kind that matches the real type at the link path is applied."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".cfg").mkdir()
    spec = LinkSpec(link=".cfg", target=str(tmp_path / "ext" / "cfg"), kind="dir", migrate=False)
    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".cfg").is_symlink()


def test_explicit_kind_contradicting_reality_is_per_link_error(tmp_path: Path):
    """F8: kind:file on a real dir is a typed per-link KindMismatchError, not a crash."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".cfg").mkdir()
    spec = LinkSpec(link=".cfg", target=str(tmp_path / "ext" / "cfg"), kind="file", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))
    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], KindMismatchError)


def test_auto_detection_uses_real_type_at_link(tmp_path: Path):
    """auto kind derives from sniff_type of the real content at the link path."""
    project = tmp_path / "proj"
    project.mkdir()

    dir_link = project / ".notes"
    dir_link.mkdir()
    assert sniff_type(dir_link) == "dir"
    spec_dir = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="auto", migrate=False)
    assert apply_all(project, [spec_dir], ctx_for(project)).failed == []
    assert (project / ".notes").is_symlink()

    file_link = project / ".env"
    file_link.write_text("KEY=val", encoding="utf-8")
    assert sniff_type(file_link) == "file"
    spec_file = LinkSpec(link=".env", target=str(tmp_path / "ext" / "env"), kind="auto", migrate=False)
    result = apply_all(project, [spec_file], ctx_for(project), force=True)
    assert result.failed == []
    assert (project / ".env").is_symlink()


def test_dot_folder_heuristic_for_missing_link(tmp_path: Path):
    """A missing dot-folder link defaults to a dir target (heuristic preserved)."""
    project = tmp_path / "proj"
    project.mkdir()
    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="auto", migrate=False)
    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".notes").is_symlink()
    assert (tmp_path / "ext" / "notes").is_dir()


def test_detect_kind_from_existing_link_type(tmp_path: Path):
    """auto kind derives from the link path when it exists."""
    spec = LinkSpec(link="x", target="y", kind="auto")
    link = tmp_path / "x"
    link.mkdir()
    assert detect_kind(spec, link, tmp_path / "y") == "dir"


def test_detect_kind_from_existing_target_type(tmp_path: Path):
    """auto kind falls back to the target path type when the link is missing."""
    spec = LinkSpec(link="x", target="y", kind="auto")
    target = tmp_path / "y"
    target.write_text("f", encoding="utf-8")
    assert detect_kind(spec, tmp_path / "x", target) == "file"


def test_detect_kind_fallback_to_file(tmp_path: Path):
    """Non-dot missing link with no existing target defaults to file."""
    spec = LinkSpec(link="env", target="y", kind="auto")
    assert detect_kind(spec, tmp_path / "env", tmp_path / "y") == "file"
