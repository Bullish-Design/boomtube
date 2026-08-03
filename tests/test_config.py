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


def test_version_yes_fails(tmp_path: Path):
    """F24: PyYAML 1.1 bool `yes` must not be silently coerced to version 1."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: yes
links:
  - link: ".notes"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_shadowing_project_root_var_fails(tmp_path: Path):
    """F16: user vars must not override the project_root builtin."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
vars:
  project_root: "/evil"
links:
  - link: ".notes"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_shadowing_project_name_var_fails(tmp_path: Path):
    """F16: user vars must not override the project_name builtin."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
vars:
  project_name: "evil"
links:
  - link: ".notes"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_empty_target_fails(tmp_path: Path):
    """F13: empty target would create a self-referential symlink; rejected at validation."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
    target: ""
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_whitespace_target_fails(tmp_path: Path):
    """F13: whitespace-only target is empty after strip; rejected at validation."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
    target: "   "
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_dotdot_link_fails(tmp_path: Path):
    """F3: `../outside` escapes the project root; rejected at validation."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "../outside"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_dot_link_fails(tmp_path: Path):
    """F4: `link: .` would target the project root itself; rejected at validation."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "."
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_dotdot_component_link_fails(tmp_path: Path):
    """F3: a `..` component anywhere in the link is rejected."""
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "a/../../b"
    target: "~/Notes"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)
