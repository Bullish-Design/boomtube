"""H6a: empty target '' -> normalized to project root -> symlink to self, recursion trap."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt6a-"))
proj = root/"proj"; proj.mkdir()

spec = LinkSpec(link=".notes", target="", kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
apply_all(proj, [spec], ctx)
link = proj/".notes"
print("link is symlink:", link.is_symlink())
print("symlink target:", link.readlink())
print("target == project root:", link.resolve() == proj.resolve())
# Consequence: recursive walk loops
print("resolving .notes ->", link.resolve())
shutil.rmtree(root, ignore_errors=True)
