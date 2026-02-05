from __future__ import annotations

from pathlib import Path

from boomtube.apply import detect_kind
from boomtube.models import LinkSpec


def test_detect_kind_prefers_explicit(tmp_path: Path):
    spec = LinkSpec(link="x", target="y", kind="file")
    assert detect_kind(spec, tmp_path / "x", tmp_path / "y") == "file"


def test_detect_kind_from_existing_link(tmp_path: Path):
    link = tmp_path / ".notes"
    link.mkdir()
    spec = LinkSpec(link=".notes", target="/tmp/t", kind="auto")
    assert detect_kind(spec, link, tmp_path / "t") == "dir"


def test_detect_kind_fallback_dotfolder(tmp_path: Path):
    spec = LinkSpec(link=".notes", target="/tmp/t", kind="auto")
    assert detect_kind(spec, tmp_path / ".notes", tmp_path / "t") == "dir"
