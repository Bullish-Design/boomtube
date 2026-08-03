from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from boomtube.apply import apply_all
from boomtube.config import ConfigError, load_config
from boomtube.models import BoomtubeConfig, LinkSpec
from boomtube.planning import PlanError, _common_path, build_plan
from boomtube.resolve import VarResolutionError


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def ctx_for(project_root: Path) -> dict[str, str]:
    return {"project_root": str(project_root), "project_name": project_root.name}


def make_cfg(links: list[dict]) -> BoomtubeConfig:
    return BoomtubeConfig(version=1, vars={}, links=[LinkSpec(**item) for item in links])


def tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | None, str | None]]:
    """Snapshot of a tree: relpath -> (kind, bytes-or-None, symlink-target-or-None)."""
    out: dict[str, tuple[str, bytes | None, str | None]] = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            out[rel] = ("symlink", None, str(p.readlink()))
        elif p.is_file():
            out[rel] = ("file", p.read_bytes(), None)
        elif p.is_dir():
            out[rel] = ("dir", None, None)
    return out


# --- I1 geometry: link escaping / root (F3, F4) -----------------------------

@pytest.mark.parametrize(
    "link",
    [".", "..", "../outside", "a/../../b", "a/../..", "..", "x/.."],
)
def test_unsafe_link_rejected_at_model(link: str):
    with pytest.raises(ValidationError):
        LinkSpec(link=link, target="/somewhere/else")


def test_dotdot_link_rejected_via_config(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "../outside"
    target: "/somewhere/else"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_dot_link_rejected_via_config(tmp_path: Path):
    cfg = write(
        tmp_path / "boomtube.yaml",
        """
version: 1
links:
  - link: "."
    target: "/somewhere/else"
""",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_stale_symlink_at_link_path_is_replaceable(tmp_path: Path):
    """A stale symlink at the link path (even one pointing at the project root) is
    replaced by unlink, never rmtree'd, so preflight must accept it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "loop").symlink_to(proj)
    (proj / "README.md").write_text("keep", encoding="utf-8")
    cfg = make_cfg([{"link": "loop", "target": str(tmp_path / "ext"), "kind": "dir"}])
    plan = build_plan(proj, cfg, ctx_for(proj))
    raw = proj / "loop"
    assert plan[0].link_path == raw.parent.resolve(strict=False) / raw.name
    apply_all(proj, [plan[0].spec], ctx_for(proj))
    assert (proj / "loop").is_symlink()
    assert (proj / "loop").resolve(strict=False) == (tmp_path / "ext").resolve(strict=False)
    assert (proj / "README.md").read_text(encoding="utf-8") == "keep"


def test_link_resolving_to_root_via_symlink_parent_rejected(tmp_path: Path):
    """link 'loop/proj' where loop -> root's parent resolves the link to the project
    root itself; must be rejected (F4 defense in depth)."""
    root = tmp_path / "x"
    proj = root / "proj"
    proj.mkdir(parents=True)
    (proj / "loop").symlink_to(root, target_is_directory=True)
    cfg = make_cfg([{"link": "loop/proj", "target": "/y", "kind": "dir"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_link_escaping_via_symlink_parent_rejected(tmp_path: Path):
    """link: out/x where out -> sibling dir outside the project must be a PlanError (F3)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (proj / "out").symlink_to(outside, target_is_directory=True)
    cfg = make_cfg([{"link": "out/x", "target": "/y", "kind": "file"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


# --- I1 geometry: target (F13, F1) ------------------------------------------

def test_empty_target_rejected_at_model():
    with pytest.raises(ValidationError):
        LinkSpec(link=".notes", target="")


def test_whitespace_target_rejected_at_model():
    with pytest.raises(ValidationError):
        LinkSpec(link=".notes", target="   ")


def test_rendered_empty_target_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": "{empty}", "kind": "dir"}])
    ctx = {**ctx_for(proj), "empty": ""}
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx)


def test_dot_target_rejected(tmp_path: Path):
    """target: '.' normalizes to the project root itself (F13)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": ".", "kind": "dir"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_target_equal_to_root_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": str(proj), "kind": "dir"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_target_inside_link_rejected(tmp_path: Path):
    """repro1 (F1): target .notes/backup lies inside the link tree .notes."""
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": ".notes/backup", "kind": "dir", "migrate": True}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_link_inside_target_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": "notes/inner", "target": "notes", "kind": "dir"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_link_equals_target_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": ".notes", "kind": "dir"}])
    with pytest.raises(PlanError):
        build_plan(proj, cfg, ctx_for(proj))


def test_disjoint_link_and_target_accepted(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": str(tmp_path / "ext" / "notes"), "kind": "dir"}])
    plan = build_plan(proj, cfg, ctx_for(proj))
    assert len(plan) == 1


def test_common_path_valueerror_treated_as_disjoint():
    """Different drives / mixed absolute+relative -> ValueError -> disjoint (None)."""
    assert _common_path([Path("/abs/x"), Path("rel/y")]) is None


def test_valid_plan_fields(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = make_cfg([{"link": ".notes", "target": "{notes}/x", "kind": "dir", "migrate": True}])
    ctx = {**ctx_for(proj), "notes": str(tmp_path / "ext")}
    plan = build_plan(proj, cfg, ctx)
    assert len(plan) == 1
    pl = plan[0]
    assert pl.link_path == (proj / ".notes").resolve(strict=False)
    assert pl.target_path == (tmp_path / "ext" / "x").resolve(strict=False)
    assert pl.migrate is True
    assert pl.spec is cfg.links[0]


# --- F6: missing var in target is a preflight error (repro4 case 2) ----------

def test_missing_var_in_target_is_preflight_error(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("KEY=val", encoding="utf-8")
    spec = LinkSpec(link=".env", target="{undefined_var}/x.env", kind="file", migrate=True)
    before = tree_snapshot(proj)
    with pytest.raises(VarResolutionError):
        apply_all(proj, [spec], ctx_for(proj))
    assert tree_snapshot(proj) == before


# --- F1: overlapping target is a preflight rejection with zero mutation (repro1) ---

def test_apply_all_rejects_target_inside_link_without_mutation(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    link_dir = proj / ".notes"
    link_dir.mkdir()
    (link_dir / "idea.txt").write_text("my precious notes", encoding="utf-8")
    (link_dir / "backup").mkdir()
    (link_dir / "backup" / "old.txt").write_text("old backup data", encoding="utf-8")

    spec = LinkSpec(link=".notes", target=".notes/backup", kind="dir", migrate=True)
    before = tree_snapshot(proj)
    with pytest.raises(PlanError):
        apply_all(proj, [spec], ctx_for(proj))
    assert tree_snapshot(proj) == before
    assert (proj / ".notes" / "idea.txt").read_text(encoding="utf-8") == "my precious notes"


# --- F3: link escaping project root is rejected before any mutation (repro3/3b) ---

def test_apply_all_rejects_dotdot_link_before_mutation(tmp_path: Path):
    root = tmp_path
    proj = root / "proj"
    proj.mkdir()
    outside = root / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("OUTSIDE-PROJECT USER DATA", encoding="utf-8")

    before = tree_snapshot(root)
    with pytest.raises(ValidationError):
        LinkSpec(link="../outside", target=str(root / "ext" / "mirror"), kind="dir", migrate=True)
    assert tree_snapshot(root) == before
