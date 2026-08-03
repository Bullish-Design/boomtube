from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from boomtube.cli import app


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_apply_subcommand_works(tmp_path: Path):
    """F7: `boomtube apply` must dispatch to the apply subcommand under typer 0.27.1."""
    proj = tmp_path / "proj"
    proj.mkdir()
    target = tmp_path / "ext" / "notes"
    write(
        proj / "boomtube.yaml",
        f"""
version: 1
links:
  - link: ".notes"
    target: "{target}"
    kind: dir
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 0, result.output
    assert (proj / ".notes").is_symlink()


def test_bare_invocation_shows_help_and_does_not_apply(tmp_path: Path):
    """F7: bare `boomtube` must print help instead of auto-applying on the cwd."""
    proj = tmp_path / "proj"
    proj.mkdir()
    write(proj / "boomtube.yaml", "version: 1\nlinks:\n  - link: '.notes'\n    target: '/tmp/x'\n")
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output
    assert "apply" in result.output
    # No auto-apply happened anywhere.
    assert not (proj / ".notes").exists()


def test_apply_help_works(tmp_path: Path):
    result = CliRunner().invoke(app, ["apply", "--help"])
    assert result.exit_code == 0
    assert "--project-root" in result.output


def test_config_error_exits_2(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    write(proj / "boomtube.yaml", "version: 99\nlinks:\n  - link: '.notes'\n    target: '/x'\n")
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 2


def test_missing_var_exits_2(tmp_path: Path):
    """F6: missing var in target surfaces at preflight as exit 2, before any mutation."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("KEY=val", encoding="utf-8")
    write(
        proj / "boomtube.yaml",
        """
version: 1
links:
  - link: ".env"
    target: "{nope}/x.env"
    kind: file
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 2
    assert (proj / ".env").read_text(encoding="utf-8") == "KEY=val"
    assert not (proj / ".env").is_symlink()


def test_overlapping_target_exits_2(tmp_path: Path):
    """F1: target inside link tree is rejected at preflight (exit 2), project untouched."""
    proj = tmp_path / "proj"
    proj.mkdir()
    write(
        proj / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
    target: ".notes/backup"
    kind: dir
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 2
    assert not (proj / ".notes").exists() or not (proj / ".notes").is_symlink()


def test_version_yes_exits_2(tmp_path: Path):
    """F24: `version: yes` (bool) is rejected at config load -> exit 2."""
    proj = tmp_path / "proj"
    proj.mkdir()
    write(
        proj / "boomtube.yaml",
        """
version: yes
links:
  - link: ".notes"
    target: "/x"
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 2


def test_migrate_false_refusal_exits_5(tmp_path: Path):
    """F2/repro2 via CLI: migrate:false + real content -> refusal, exit 5, data intact."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".notes").mkdir()
    (proj / ".notes" / "diary.txt").write_text("10 years of journals", encoding="utf-8")
    write(
        proj / "boomtube.yaml",
        """
version: 1
links:
  - link: ".notes"
    target: "/tmp/boomtube-never-target"
    kind: dir
    migrate: false
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 5
    assert (proj / ".notes" / "diary.txt").read_text(encoding="utf-8") == "10 years of journals"
    assert not (proj / ".notes").is_symlink()


def test_per_link_failure_continues_and_exits_5(tmp_path: Path, caplog):
    """F12/repro15 via CLI: .bad fails, .good applies, exit 5 with summary."""
    import logging

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".bad").write_text("x")
    write(
        proj / "boomtube.yaml",
        f"""
version: 1
links:
  - link: ".bad"
    target: "{tmp_path / 't1'}"
    kind: dir
    migrate: true
  - link: ".good"
    target: "{tmp_path / 't2'}"
    kind: dir
    migrate: true
""",
    )
    with caplog.at_level(logging.ERROR):
        result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 5
    assert (proj / ".good").is_symlink()
    assert (proj / ".bad").is_file()
    assert any("applied 1/2 links" in r.message for r in caplog.records)
    assert any("failed to apply link" in r.message for r in caplog.records)


def test_force_flag_overrides_migrate_false_refusal(tmp_path: Path):
    """F2 --force via CLI: replace-without-migrating succeeds (exit 0)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("KEY=val", encoding="utf-8")
    write(
        proj / "boomtube.yaml",
        """
version: 1
links:
  - link: ".env"
    target: "/tmp/boomtube-never-target2"
    kind: file
    migrate: false
""",
    )
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj), "--force"])
    assert result.exit_code == 0, result.output
    assert (proj / ".env").is_symlink()


def test_oserror_maps_to_exit_4(tmp_path: Path, monkeypatch):
    """F19: an OSError outside the per-link loop maps to exit 4."""
    import boomtube.cli as cli_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    write(proj / "boomtube.yaml", "version: 1\nlinks:\n  - link: '.notes'\n    target: '/x'\n")

    def boom(root, cfg, ctx):
        raise OSError("simulated I/O failure")

    monkeypatch.setattr(cli_mod, "build_plan", boom)
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 4


def test_permission_error_maps_to_exit_3(tmp_path: Path, monkeypatch):
    """F19: a PermissionError maps to exit 3."""
    import boomtube.cli as cli_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    write(proj / "boomtube.yaml", "version: 1\nlinks:\n  - link: '.notes'\n    target: '/x'\n")

    def boom(root, cfg, ctx):
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(cli_mod, "build_plan", boom)
    result = CliRunner().invoke(app, ["apply", "--project-root", str(proj)])
    assert result.exit_code == 3
