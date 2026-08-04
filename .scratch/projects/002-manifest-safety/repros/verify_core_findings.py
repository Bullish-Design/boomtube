"""Post-fix verification for the 002 "manifest safety" findings (core).

Each finding's ORIGINAL bug assertion is run against the fixed package; a
finding is only CONFIRMED (i.e. the bug still exists) if the buggy outcome
still occurs. All should print NOT CONFIRMED.
"""
import os, tempfile
from pathlib import Path
from boomtube.models import LinkSpec, BoomtubeConfig
from boomtube.planning import build_plan, PlannedLink, PlanError
from boomtube.apply import apply_link, apply_plan, MigrateDisabledError
from boomtube.migrate import UnsupportedLinkTypeError
import logging; logging.disable(logging.CRITICAL)

def mkproj():
    r = Path(tempfile.mkdtemp())/"proj"; r.mkdir(); return r

print("F1: non-regular content in a migrated dir")
r = mkproj(); outside = Path(tempfile.mkdtemp()); (outside/"real.txt").write_text("important")
l = r/".notes"; l.mkdir()
(l/"ln-to-real").symlink_to(outside/"real.txt"); (l/"empty-subdir").mkdir()
(l/"data.conflict-from-project-deadbeef").write_text("user file")
t = Path(tempfile.mkdtemp())/"T"
apply_link(r, PlannedLink(spec=LinkSpec(link=".notes", target=str(t)), link_path=l, target_path=t, migrate=True))
ok = (t/"ln-to-real").is_symlink() and (t/"empty-subdir").is_dir() \
     and (t/"data.conflict-from-project-deadbeef").read_text()=="user file"
print(f"   symlink/empty-dir/conflict preserved: {ok}")
print(f"   VERDICT: {'CONFIRMED - entries still destroyed' if not ok else 'NOT CONFIRMED'}")

print("F1b: special file inside a migrated dir")
r = mkproj(); l = r/".notes"; l.mkdir(); os.mkfifo(l/"myfifo")
t = Path(tempfile.mkdtemp())/"T"
try:
    apply_link(r, PlannedLink(spec=LinkSpec(link=".notes", target=str(t)), link_path=l, target_path=t, migrate=True))
    print(f"   VERDICT: CONFIRMED - FIFO silently deleted")
except UnsupportedLinkTypeError as e:
    print(f"   refused with UnsupportedLinkTypeError: {e}")
    print("   VERDICT: NOT CONFIRMED")

print("F2: migrate:false, dir of symlinks, no --force")
r = mkproj(); o = Path(tempfile.mkdtemp()); (o/"x").write_text("payload")
l = r/".cfg"; l.mkdir()
for n in ("s1","s2","s3"): (l/n).symlink_to(o/"x")
t = Path(tempfile.mkdtemp())/"T"
try:
    apply_link(r, PlannedLink(spec=LinkSpec(link=".cfg", target=str(t), migrate=False), link_path=l, target_path=t, migrate=False))
    print(f"   no refusal raised; target={sorted(p.name for p in t.rglob('*'))}")
    print("   VERDICT: CONFIRMED - 3 symlinks destroyed without --force")
except MigrateDisabledError as e:
    print(f"   refused with MigrateDisabledError: {e}")
    print("   VERDICT: NOT CONFIRMED")

print("F4: repointing an existing symlink to a new target")
r = mkproj(); t = Path(tempfile.mkdtemp()); l = r/".notes"; l.mkdir(); (l/"a.txt").write_text("data")
apply_link(r, PlannedLink(spec=LinkSpec(link=".notes", target=str(t/"old")), link_path=l, target_path=t/"old", migrate=True))
apply_link(r, PlannedLink(spec=LinkSpec(link=".notes", target=str(t/"new")), link_path=l, target_path=t/"new", migrate=True))
print(f"   .notes -> {os.readlink(l)}   target_exists={(t/'new').is_dir()}")
print(f"   VERDICT: {'CONFIRMED - dangling symlink, exit 0' if (not l.exists() or not (t/'new').is_dir()) else 'NOT CONFIRMED'}")

print("F5a: duplicate link paths")
r = mkproj(); t = Path(tempfile.mkdtemp()); a = r/".notes"; a.mkdir(); (a/"keep.txt").write_text("A")
cfg = BoomtubeConfig(version=1, vars={}, links=[
    LinkSpec(link=".notes", target=str(t/"one"), name="first"),
    LinkSpec(link=".notes", target=str(t/"two"), name="second")])
try:
    planned = build_plan(r, cfg, {}); apply_plan(r, planned)
    print(f"   preflight accepted={len(planned)}")
    print("   VERDICT: CONFIRMED - duplicate link paths accepted")
except PlanError as e:
    print(f"   preflight rejected: {e}")
    print("   VERDICT: NOT CONFIRMED")

print("F5b: nested targets T/sub and T")
r = mkproj(); T = Path(tempfile.mkdtemp())/"T"
a = r/".a"; a.mkdir(); (a/"a.txt").write_text("A"); b = r/".b"; b.mkdir(); (b/"b.txt").write_text("B")
cfg = BoomtubeConfig(version=1, vars={}, links=[LinkSpec(link=".a", target=str(T/"sub")), LinkSpec(link=".b", target=str(T))])
try:
    planned = build_plan(r, cfg, {}); apply_plan(r, planned, force=True)
    print("   VERDICT: CONFIRMED - nested targets accepted")
except PlanError as e:
    print(f"   preflight rejected: {e}")
    print("   VERDICT: NOT CONFIRMED")

print("F9: pydantic extra fields")
from pydantic import ValidationError
try:
    s = LinkSpec.model_validate({"link":".n","target":"/t","migrat":False})
    print(f"   typo 'migrat: false' accepted; spec.migrate={s.migrate}")
    print("   VERDICT: CONFIRMED - typo silently ignored, migration stays ON")
except ValidationError:
    print("   VERDICT: NOT CONFIRMED - rejected")
