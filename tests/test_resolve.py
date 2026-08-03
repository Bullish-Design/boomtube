from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.resolve import VarResolutionError, build_context, resolve_vars


def test_builtins_resolve(tmp_path: Path):
    ctx = build_context(tmp_path, {})
    assert ctx["project_root"] == str(tmp_path)
    assert ctx["project_name"] == tmp_path.name


def test_user_var_referencing_other_var(tmp_path: Path):
    ctx = build_context(
        tmp_path,
        {
            "notes_root": "/x",
            "proj": "{notes_root}/{project_name}",
        },
    )
    assert ctx["proj"].endswith(f"/x/{tmp_path.name}")


def test_missing_var_raises(tmp_path: Path):
    with pytest.raises(VarResolutionError):
        build_context(tmp_path, {"a": "{missing}"})


def test_cycle_raises(tmp_path: Path):
    with pytest.raises(VarResolutionError):
        resolve_vars({"a": "{b}", "b": "{a}"}, {"project_root": "x", "project_name": "y"})


@pytest.mark.parametrize("bad", ["{}", "{", "{x", "{0}"])
def test_stray_braces_and_positional_fields_raise(tmp_path: Path, bad: str):
    """F5: `{}`/`{`/`{x`/`{0}` must become a typed VarResolutionError, not ValueError."""
    with pytest.raises(VarResolutionError):
        build_context(tmp_path, {"a": bad})
    with pytest.raises(VarResolutionError):
        resolve_vars({"a": bad}, {"project_root": "x", "project_name": "y"})


def test_builtins_cannot_be_overridden_in_build_context(tmp_path: Path):
    """F16: even if a user var shadows a builtin, builtins win at merge time."""
    ctx = build_context(tmp_path, {"project_root": "/evil", "project_name": "evil"})
    assert ctx["project_root"] == str(tmp_path)
    assert ctx["project_name"] == tmp_path.name


def test_render_template_normalizes_stray_braces():
    from boomtube.resolve import render, render_template

    with pytest.raises(VarResolutionError):
        render_template("{}", {})
    with pytest.raises(VarResolutionError):
        render("{", {"a": "b"})
