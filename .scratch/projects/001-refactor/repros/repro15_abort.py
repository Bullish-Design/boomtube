"""E: first failing link aborts remaining links (no per-link isolation)."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
root = Path(tempfile.mkdtemp(prefix="bt15-"))
proj = root/"proj"; proj.mkdir()
# spec1: kind=dir on a real FILE -> crashes
(proj/".bad").write_text("x")
specs = [
    LinkSpec(link=".bad", target=str(root/"t1"), kind="dir", migrate=True),
    LinkSpec(link=".good", target=str(root/"t2"), kind="dir", migrate=True),
]
try:
    apply_all(proj, specs, {"project_root": str(proj), "project_name": proj.name})
except OSError as e:
    print("apply_all aborted at first failing link:", type(e).__name__)
print(".good link created (would be if continued):", (proj/".good").is_symlink())
print(".bad still real file:", (proj/".bad").is_file())
shutil.rmtree(root, ignore_errors=True)
