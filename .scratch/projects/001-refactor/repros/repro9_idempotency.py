"""Seed7: run apply twice — second run must be no-op and keep migration results."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil, os
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt9-"))
proj = root/"proj"; proj.mkdir()
link_dir = proj/".notes"; link_dir.mkdir()
(link_dir/"a.txt").write_text("content-A", encoding="utf-8")
target = root/"ext"/"notes"; target.mkdir(parents=True)
(target/"a.txt").write_text("content-A", encoding="utf-8")
(target/"keep.txt").write_text("keep", encoding="utf-8")

spec = LinkSpec(link=".notes", target=str(target), kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}

apply_all(proj, [spec], ctx)
ino1 = os.lstat(proj/".notes").st_ino
apply_all(proj, [spec], ctx)
ino2 = os.lstat(proj/".notes").st_ino
print("run2 no-op (same inode):", ino1 == ino2)
print("keep.txt intact:", (target/"keep.txt").exists())
print("a.txt intact via link:", (proj/".notes/a.txt").exists())
# conflict-file behavior on second run with real dirs (migrate run twice directly)
from boomtube.migrate import migrate_dir
a2 = root/"a2"; b2 = root/"b2"
a2.mkdir(); b2.mkdir()
(a2/"f").write_text("aaa")
(b2/"f").write_text("bbb")
os.utime(a2/"f", (1000,1000)); os.utime(b2/"f", (1000,1000))
st1 = migrate_dir(a2, b2)
print("run1 stats:", st1)
st2 = migrate_dir(a2, b2)
print("run2 stats:", st2)
print("run2 no-op check done; conflict spread covered in repro9b")
shutil.rmtree(root, ignore_errors=True)
