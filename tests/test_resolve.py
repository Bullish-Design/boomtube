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
