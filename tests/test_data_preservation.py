from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from boomtube.apply import MigrateDisabledError, UnsupportedLinkTypeError, apply_all, detect_kind
from boomtube.cli import app
from boomtube.config import ConfigError, load_config
from boomtube.fsops import reclaim_staging_residue
from boomtube.migrate import MigrateCollisionError
from boomtube.models import LinkSpec
from boomtube.planning import PlanError

R = CliRunner()


def ctx_for(project_root: Path) -> dict[str, str]:
    return {"project_root": str(project_root), "project_name": project_root.name}


def test_symlink_inside_migrated_dir_is_preserved(tmp_path: Path):
    """F1: a symlink inside a migrated dir is copied verbatim, never followed or dropped."""
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.txt").write_text("important", encoding="utf-8")
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "ln-to-real").symlink_to(outside / "real.txt")
    (link_dir / "note.txt").write_text("hi", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "ln-to-real").is_symlink()
    assert os.readlink(target / "ln-to-real") == str(outside / "real.txt")
    assert (target / "note.txt").read_text(encoding="utf-8") == "hi"
    assert (project / ".notes").is_symlink()


def test_empty_subdir_is_preserved(tmp_path: Path):
    """F1: empty directories inside a migrated tree are recreated in the target."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "empty-sub").mkdir()
    (link_dir / "note.txt").write_text("hi", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "empty-sub").is_dir()
    assert (target / "note.txt").read_text(encoding="utf-8") == "hi"


def test_conflict_named_user_file_is_preserved(tmp_path: Path):
    """F1: a user's own *.conflict-from-project-* file under the link path is real data."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "notes.conflict-from-project-deadbeef").write_text("user file", encoding="utf-8")
    (link_dir / "note.txt").write_text("hi", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "notes.conflict-from-project-deadbeef").read_text(encoding="utf-8") == "user file"
    assert (target / "note.txt").read_text(encoding="utf-8") == "hi"


def test_special_file_inside_tree_is_refused(tmp_path: Path):
    """F1: a FIFO nested in a migrated tree is a refusal, never silent loss."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "note.txt").write_text("hi", encoding="utf-8")
    os.mkfifo(link_dir / "myfifo")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], UnsupportedLinkTypeError)
    assert (link_dir / "myfifo").exists()
    assert (link_dir / "note.txt").read_text(encoding="utf-8") == "hi"  # nothing mutated
    assert not (project / ".notes").is_symlink()


def test_migrate_false_refuses_dir_of_symlinks(tmp_path: Path):
    """F2: migrate:false must refuse any non-empty dir, even one holding only symlinks."""
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("payload", encoding="utf-8")
    link_dir = project / ".cfg"
    link_dir.mkdir()
    for n in ("s1", "s2", "s3"):
        (link_dir / n).symlink_to(outside / "x.txt")

    spec = LinkSpec(link=".cfg", target=str(tmp_path / "ext" / "cfg"), kind="dir", migrate=False)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], MigrateDisabledError)
    assert (link_dir / "s1").is_symlink()
    assert (link_dir / "s2").is_symlink()
    assert not (project / ".cfg").is_symlink()


def test_repointing_symlink_creates_target(tmp_path: Path):
    """F4: editing target: on an existing symlink must create the new target dir."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a.txt").write_text("data", encoding="utf-8")

    target_old = tmp_path / "ext" / "old"
    spec1 = LinkSpec(link=".notes", target=str(target_old), kind="dir", migrate=True)
    result1 = apply_all(project, [spec1], ctx_for(project))
    assert result1.failed == []
    assert (project / ".notes").is_symlink()
    assert (target_old / "a.txt").read_text(encoding="utf-8") == "data"

    target_new = tmp_path / "ext" / "new"
    spec2 = LinkSpec(link=".notes", target=str(target_new), kind="dir", migrate=True)
    result2 = apply_all(project, [spec2], ctx_for(project))

    assert result2.failed == []
    assert (project / ".notes").is_symlink()
    assert os.readlink(project / ".notes") == str(target_new.resolve(strict=False))
    assert target_new.is_dir()  # F4: the new target must be created, not left dangling


def test_duplicate_link_paths_rejected_at_preflight(tmp_path: Path):
    """F5a: two links with the same link: path are rejected before any mutation."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".notes").mkdir()
    (project / ".notes" / "keep.txt").write_text("A", encoding="utf-8")

    specs = [
        LinkSpec(link=".notes", target=str(tmp_path / "ext" / "one"), name="first"),
        LinkSpec(link=".notes", target=str(tmp_path / "ext" / "two"), name="second"),
    ]
    with pytest.raises(PlanError):
        apply_all(project, specs, ctx_for(project))
    assert (project / ".notes" / "keep.txt").read_text(encoding="utf-8") == "A"
    assert not (project / ".notes").is_symlink()


def test_duplicate_target_paths_rejected_at_preflight(tmp_path: Path):
    """F5a: two links with the same target: path are rejected before any mutation."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".a").mkdir()
    (project / ".b").mkdir()
    specs = [
        LinkSpec(link=".a", target=str(tmp_path / "ext" / "T"), name="first"),
        LinkSpec(link=".b", target=str(tmp_path / "ext" / "T"), name="second"),
    ]
    with pytest.raises(PlanError):
        apply_all(project, specs, ctx_for(project))
    assert not (project / ".a").is_symlink()
    assert not (project / ".b").is_symlink()


def test_link_nested_under_another_link_rejected(tmp_path: Path):
    """F5: a link inside another link's path is rejected at preflight."""
    project = tmp_path / "proj"
    project.mkdir()
    specs = [
        LinkSpec(link="a", target=str(tmp_path / "ext" / "t1"), kind="dir", migrate=False),
        LinkSpec(link="a/b", target=str(tmp_path / "ext" / "t2"), kind="dir", migrate=False),
    ]
    with pytest.raises(PlanError):
        apply_all(project, specs, ctx_for(project))


def test_link_nested_under_another_target_rejected(tmp_path: Path):
    """F5: a link inside another link's target is rejected at preflight."""
    project = tmp_path / "proj"
    project.mkdir()
    specs = [
        LinkSpec(link=".a", target="subdir", kind="dir", migrate=False),
        LinkSpec(link="subdir/x", target=str(tmp_path / "ext" / "t2"), kind="file", migrate=False),
    ]
    with pytest.raises(PlanError):
        apply_all(project, specs, ctx_for(project))


def test_disjoint_links_still_plan_fine(tmp_path: Path):
    """F5: genuinely disjoint links are unaffected by pairwise validation."""
    project = tmp_path / "proj"
    project.mkdir()
    specs = [
        LinkSpec(link=".a", target=str(tmp_path / "ext" / "t1"), kind="dir", migrate=False),
        LinkSpec(link=".b", target=str(tmp_path / "ext" / "t2"), kind="dir", migrate=False),
    ]
    result = apply_all(project, specs, ctx_for(project))
    assert result.failed == []
    assert (project / ".a").is_symlink()
    assert (project / ".b").is_symlink()


def test_nested_targets_rejected_at_preflight(tmp_path: Path):
    """F5b: nested target paths (T/sub inside T) are rejected before any mutation."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".a").mkdir()
    (project / ".a" / "a.txt").write_text("A", encoding="utf-8")
    (project / ".b").mkdir()
    (project / ".b" / "b.txt").write_text("B", encoding="utf-8")

    T = tmp_path / "ext" / "T"
    specs = [
        LinkSpec(link=".a", target=str(T / "sub"), kind="dir", migrate=True),
        LinkSpec(link=".b", target=str(T), kind="dir", migrate=True),
    ]
    with pytest.raises(PlanError):
        apply_all(project, specs, ctx_for(project))
    assert (project / ".a" / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project / ".b" / "b.txt").read_text(encoding="utf-8") == "B"
    assert not (project / ".a").is_symlink()
    assert not (project / ".b").is_symlink()


def test_reclaim_glob_metachars_escaped(tmp_path: Path):
    """F6: a link named `[mn]` must not make the reclaim glob touch `n.bt-staging-*`."""
    victim = tmp_path / "n.bt-staging-999"
    victim.mkdir()
    (victim / "only-copy.txt").write_text("unique data", encoding="utf-8")
    reclaim_staging_residue(tmp_path / "[mn]")
    assert victim.exists()
    assert (victim / "only-copy.txt").read_text(encoding="utf-8") == "unique data"


@pytest.mark.skipif(os.geteuid() == 0, reason="chmod-based permission test is ineffective as root")
def test_permission_error_during_apply_exits_3(tmp_path: Path):
    """F7: a real PermissionError during apply maps to exit 3."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".notes").mkdir()
    (project / ".notes" / "f.txt").write_text("x", encoding="utf-8")
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "sub" / "T"
    (project / "boomtube.yaml").write_text(
        f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{target}'\n    kind: dir\n",
        encoding="utf-8",
    )
    os.chmod(locked, 0o000)
    try:
        result = R.invoke(app, ["apply", "--project-root", str(project)])
    finally:
        os.chmod(locked, 0o755)
    assert result.exit_code == 3
    assert (project / ".notes" / "f.txt").read_text(encoding="utf-8") == "x"
    assert not (project / ".notes").is_symlink()


@pytest.mark.skipif(os.geteuid() == 0, reason="chmod-based permission test is ineffective as root")
def test_unreadable_config_exits_3(tmp_path: Path):
    """F7: an unreadable config surfaces as a real PermissionError -> exit 3."""
    project = tmp_path / "proj"
    project.mkdir()
    cfgf = project / "boomtube.yaml"
    cfgf.write_text("version: 1\nlinks:\n  - link: '.n'\n    target: '/t'\n", encoding="utf-8")
    os.chmod(cfgf, 0o000)
    try:
        result = R.invoke(app, ["apply", "--project-root", str(project)])
    finally:
        os.chmod(cfgf, 0o644)
    assert result.exit_code == 3


def test_explicit_project_root_wins_over_config_parent(tmp_path: Path):
    """F8: --project-root A --config B/boomtube.yaml must create the link in A."""
    A = tmp_path / "A"
    A.mkdir()
    B = tmp_path / "B"
    B.mkdir()
    T = tmp_path / "ext" / "T"
    (B / "boomtube.yaml").write_text(
        f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{T}'\n    kind: dir\n",
        encoding="utf-8",
    )
    result = R.invoke(app, ["apply", "--project-root", str(A), "--config", str(B / "boomtube.yaml")])
    assert result.exit_code == 0, result.output
    assert (A / ".notes").is_symlink()
    assert not (B / ".notes").exists()


def test_unknown_link_field_rejected(tmp_path: Path):
    """F9: a typo like `migrat: false` must be rejected, not silently ignored."""
    cfg = tmp_path / "boomtube.yaml"
    cfg.write_text(
        "version: 1\nlinks:\n  - link: '.notes'\n    target: '/x'\n    migrat: false\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_unknown_top_level_key_rejected(tmp_path: Path):
    """F9: an unknown top-level config key is rejected, with the key named."""
    cfg = tmp_path / "boomtube.yaml"
    cfg.write_text(
        "version: 1\nmigrate_all: false\nlinks:\n  - link: '.notes'\n    target: '/x'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as ei:
        load_config(cfg)
    assert "migrate_all" in str(ei.value)


def test_unknown_link_field_error_names_key(tmp_path: Path):
    """F9: the ConfigError names the offending field."""
    cfg = tmp_path / "boomtube.yaml"
    cfg.write_text(
        "version: 1\nlinks:\n  - link: '.notes'\n    target: '/x'\n    migrat: false\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as ei:
        load_config(cfg)
    assert "migrat" in str(ei.value)


def test_detect_kind_uses_basename():
    """F10: the dot-heuristic must use the basename, not the whole link string."""
    top = detect_kind(LinkSpec(link=".nvim", target="/t", kind="auto"), Path("/nonexistent1"), Path("/nonexistent2"))
    nested = detect_kind(
        LinkSpec(link="config/.nvim", target="/t", kind="auto"), Path("/nonexistent1"), Path("/nonexistent2")
    )
    plain = detect_kind(
        LinkSpec(link="config/notes", target="/t", kind="auto"), Path("/nonexistent1"), Path("/nonexistent2")
    )
    assert top == "dir"
    assert nested == "dir"
    assert plain == "file"


# --- Step 9: NUL-byte validation (F15) ---------------------------------------

def test_nul_in_link_exits_2_not_traceback(tmp_path: Path):
    """F15: a NUL byte in `link` (via YAML's \u0000 escape) is rejected -> exit 2."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "boomtube.yaml").write_text(
        'version: 1\nlinks:\n  - link: "a\\u0000b"\n    target: "/x"\n', encoding="utf-8"
    )
    result = R.invoke(app, ["apply", "--project-root", str(project)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_nul_in_target_exits_2_not_traceback(tmp_path: Path):
    """F15: a NUL byte in `target` (via YAML's \u0000 escape) is rejected -> exit 2."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "boomtube.yaml").write_text(
        'version: 1\nlinks:\n  - link: ".n"\n    target: "/x\\u0000y"\n', encoding="utf-8"
    )
    result = R.invoke(app, ["apply", "--project-root", str(project)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_nul_via_var_in_rendered_target_exits_2(tmp_path: Path):
    """F15 (defense in depth): a NUL injected through a `{var}` is a PlanError -> exit 2."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "boomtube.yaml").write_text(
        'version: 1\nvars:\n  evil: "x\\u0000y"\nlinks:\n  - link: ".n"\n    target: "{evil}/env"\n',
        encoding="utf-8",
    )
    result = R.invoke(app, ["apply", "--project-root", str(project)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_unique_path_skips_dangling_symlink(tmp_path: Path):
    """F15: unique_path treats a dangling symlink at the candidate as taken."""
    from boomtube.util import unique_path

    base = tmp_path / "f"
    base.symlink_to(tmp_path / "ghost")
    got = unique_path(base)
    assert got == tmp_path / "f-1"
    assert not got.exists()


# --- Step 2: manifest-based seed/verify behaviors ------------------------------------

def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | None, str | None]]:
    out: dict[str, tuple[str, bytes | None, str | None]] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            out[rel] = ("symlink", None, str(p.readlink()))
        elif p.is_file():
            out[rel] = ("file", p.read_bytes(), None)
        elif p.is_dir():
            out[rel] = ("dir", None, None)
    return out


def test_relative_symlink_stays_relative(tmp_path: Path):
    """Relative intra-tree symlinks are recreated verbatim, never rewritten absolute (2c)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "target.txt").write_text("x", encoding="utf-8")
    (link_dir / "ln").symlink_to("target.txt")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "ln").is_symlink()
    assert os.readlink(target / "ln") == "target.txt"
    assert (target / "target.txt").read_text(encoding="utf-8") == "x"


def test_broken_symlink_is_preserved(tmp_path: Path):
    """Broken symlinks inside a migrated tree are preserved as-is (2c)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "ln").symlink_to(tmp_path / "ghost-target")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "ln").is_symlink()
    assert os.readlink(target / "ln") == str(tmp_path / "ghost-target")


def test_nested_empty_dir_chain_recreated(tmp_path: Path):
    """An a/b/c empty dir chain is recreated in the target (F1)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a" / "b" / "c").mkdir(parents=True)

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert (target / "a" / "b" / "c").is_dir()
    assert (target / "a" / "b").is_dir()
    assert (target / "a").is_dir()


def test_dir_mode_preserved(tmp_path: Path):
    """Directory mode/mtime are carried to the target (best effort) (2c)."""
    import stat as stat_mod

    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    sub = link_dir / "sub"
    sub.mkdir()
    sub.chmod(0o751)
    (link_dir / "note.txt").write_text("x", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert result.failed == []
    target = tmp_path / "ext" / "notes"
    assert stat_mod.S_IMODE((target / "sub").stat().st_mode) == 0o751


def test_rerun_of_completed_migration_is_noop(tmp_path: Path):
    """Re-running a completed migration changes nothing (idempotency)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a.txt").write_text("a", encoding="utf-8")
    (link_dir / "ln").symlink_to("a.txt")
    (link_dir / "empty").mkdir()

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    ctx = ctx_for(project)
    r1 = apply_all(project, [spec], ctx)
    assert r1.failed == []
    target = tmp_path / "ext" / "notes"
    before = _tree_snapshot(target)

    r2 = apply_all(project, [spec], ctx)
    assert r2.failed == []
    assert _tree_snapshot(target) == before


def test_fifo_nested_three_deep_refused_with_path(tmp_path: Path):
    """A FIFO nested three levels deep is refused, with the rel path in the message (2a)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a" / "b" / "c").mkdir(parents=True)
    os.mkfifo(link_dir / "a" / "b" / "c" / "pipe")

    spec = LinkSpec(link=".notes", target=str(tmp_path / "ext" / "notes"), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    err = result.failed[0][1]
    assert isinstance(err, UnsupportedLinkTypeError)
    assert "a/b/c/pipe" in str(err)
    assert not (project / ".notes").is_symlink()


def test_target_with_only_symlinks_counts_as_populated(tmp_path: Path):
    """A target containing only symlinks now counts as populated (more conservative, 2b)."""
    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "a.txt").write_text("a", encoding="utf-8")
    target = tmp_path / "ext" / "notes"
    target.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "ln").symlink_to(outside)

    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
    result = apply_all(project, [spec], ctx_for(project))

    assert len(result.failed) == 1
    assert isinstance(result.failed[0][1], MigrateCollisionError)
    assert (target / "ln").is_symlink()  # untouched
    assert (link_dir / "a.txt").read_text(encoding="utf-8") == "a"
    assert not (project / ".notes").is_symlink()


# --- Step 5: symlink branch / _ensure_target (F4, F13) -------------------------

def test_repointing_symlink_warns_naming_old_target(tmp_path: Path, caplog):
    """F4: repointing logs a warning that names the previous target."""
    import logging

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".notes").mkdir()
    (project / ".notes" / "a.txt").write_text("data", encoding="utf-8")

    target_old = tmp_path / "ext" / "old"
    spec1 = LinkSpec(link=".notes", target=str(target_old), kind="dir", migrate=True)
    assert apply_all(project, [spec1], ctx_for(project)).failed == []

    target_new = tmp_path / "ext" / "new"
    spec2 = LinkSpec(link=".notes", target=str(target_new), kind="dir", migrate=True)
    with caplog.at_level(logging.WARNING):
        result2 = apply_all(project, [spec2], ctx_for(project))
    assert result2.failed == []
    assert (project / ".notes").is_symlink()
    assert any("repointed" in r.message and str(target_old.resolve(strict=False)) in r.message for r in caplog.records)


def test_recreate_deleted_target_dir_for_correct_symlink(tmp_path: Path):
    """F4: a correct symlink whose target dir was deleted is recreated on re-apply."""
    import shutil

    project = tmp_path / "proj"
    project.mkdir()
    target = tmp_path / "ext" / "notes"
    target.mkdir(parents=True)
    (project / ".notes").symlink_to(target)

    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
    assert apply_all(project, [spec], ctx_for(project)).failed == []
    shutil.rmtree(target)
    assert (project / ".notes").is_symlink() and not target.exists()

    result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert target.is_dir()  # recreated by _ensure_target
    assert (project / ".notes").is_symlink()


def test_dangling_file_symlink_reported_but_exit_zero(tmp_path: Path, caplog):
    """F13: dangling file symlinks are reported as a warning; the run still succeeds."""
    import logging

    project = tmp_path / "proj"
    project.mkdir()
    spec = LinkSpec(link=".env", target=str(tmp_path / "ext" / "missing.env"), kind="file", migrate=True)
    with caplog.at_level(logging.WARNING):
        result = apply_all(project, [spec], ctx_for(project))
    assert result.failed == []
    assert (project / ".env").is_symlink()
    assert any("do not exist yet" in r.message for r in caplog.records)


def test_force_conflict_warning_logs_count(tmp_path: Path, caplog):
    """The per-link summary warns when conflicts were created under --force."""
    import logging

    project = tmp_path / "proj"
    project.mkdir()
    link_dir = project / ".notes"
    link_dir.mkdir()
    (link_dir / "f.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "ext" / "notes"
    target.mkdir(parents=True)
    (target / "f.txt").write_text("old", encoding="utf-8")
    spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)

    with caplog.at_level(logging.WARNING):
        result = apply_all(project, [spec], ctx_for(project), force=True)
    assert result.failed == []
    assert (project / ".notes").is_symlink()
    assert any("conflict file(s)" in r.message for r in caplog.records)
