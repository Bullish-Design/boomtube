"""Post-fix verification for the 002 "manifest safety" findings (CLI).

Each finding's ORIGINAL bug assertion is run against the fixed package; a
finding is only CONFIRMED (i.e. the bug still exists) if the buggy outcome
still occurs. All should print NOT CONFIRMED.
"""
import os, tempfile
from pathlib import Path
from typer.testing import CliRunner
from boomtube.cli import app
from boomtube.apply import detect_kind
from boomtube.models import LinkSpec
from boomtube.fsops import reclaim_staging_residue
R = CliRunner()

print("F7a: real PermissionError during apply -> documented exit 3?")
p = Path(tempfile.mkdtemp())/"proj"; p.mkdir()
locked = Path(tempfile.mkdtemp())/"locked"; locked.mkdir()
(p/".notes").mkdir(); (p/".notes"/"f.txt").write_text("x")
(p/"boomtube.yaml").write_text(f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{locked}/sub/T'\n")
os.chmod(locked, 0o000)
res = R.invoke(app, ["apply", "--project-root", str(p)])
os.chmod(locked, 0o755)
print(f"   exit_code={res.exit_code} (README documents 3 for permission errors)")
print(f"   VERDICT: {'CONFIRMED - exit 3 unreachable, got 5' if res.exit_code==5 else 'NOT CONFIRMED'}")

print("F7b: unreadable config -> documented exit 3?")
p = Path(tempfile.mkdtemp())/"proj"; p.mkdir()
cfgf = p/"boomtube.yaml"; cfgf.write_text("version: 1\nlinks:\n  - link: '.n'\n    target: '/t'\n")
os.chmod(cfgf, 0o000)
res = R.invoke(app, ["apply", "--project-root", str(p)])
os.chmod(cfgf, 0o644)
print(f"   exit_code={res.exit_code}")
print(f"   VERDICT: {'CONFIRMED - wrapped into ConfigError, exit 2 not 3' if res.exit_code==2 else 'NOT CONFIRMED'}")

print("F8: --config silently overrides --project-root")
A = Path(tempfile.mkdtemp())/"A"; A.mkdir()
B = Path(tempfile.mkdtemp())/"B"; B.mkdir()
T = Path(tempfile.mkdtemp())/"T"
(B/"boomtube.yaml").write_text(f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{T}'\n")
res = R.invoke(app, ["apply", "--project-root", str(A), "--config", str(B/"boomtube.yaml")])
print(f"   exit={res.exit_code}  link created in A={(A/'.notes').is_symlink()}  in B={(B/'.notes').is_symlink()}")
print(f"   VERDICT: {'CONFIRMED - --project-root silently ignored, root became config parent' if (B/'.notes').is_symlink() and not (A/'.notes').is_symlink() else 'NOT CONFIRMED'}")

print("F6: unescaped glob metachars in reclaim_staging_residue")
d = Path(tempfile.mkdtemp())
victim = d/"n.bt-staging-999"; victim.mkdir(); (victim/"only-copy.txt").write_text("unique data")
reclaim_staging_residue(d/"[mn]")
print(f"   unrelated link's residue survived={victim.exists()}")
print(f"   VERDICT: {'CONFIRMED - sibling residue deleted by glob metachar' if not victim.exists() else 'NOT CONFIRMED'}")

print("F10: detect_kind dot-heuristic uses full link string")
top = detect_kind(LinkSpec(link=".nvim", target="/t"), Path("/nonexistent1"), Path("/nonexistent2"))
nested = detect_kind(LinkSpec(link="config/.nvim", target="/t"), Path("/nonexistent1"), Path("/nonexistent2"))
print(f"   '.nvim' -> {top!r}   'config/.nvim' -> {nested!r}")
print(f"   VERDICT: {'CONFIRMED - same basename, different kind' if top!=nested else 'NOT CONFIRMED'}")
