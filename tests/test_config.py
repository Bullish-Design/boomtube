from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.config import ConfigError, load_config


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_config_loads(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
vars:
  notes_root: "~/Notes"
links:
  - name: notes
    link: ".notes"
    target: "{notes_root}/Projects/{project_name}"
    kind: dir
    migrate: true
""",
    )
    c = load_config(cfg)
    assert c.version == 1
    assert c.links[0].link == ".notes"


def test_missing_version_fails(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
links:
  - link: ".notes"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_version_not_1_fails(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 2
links:
  - link: ".notes"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_absolute_link_fails(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "/abs"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_invalid_kind_fails(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
    target: "~/Notes"
    kind: nope
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_missing_target_fails(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)
