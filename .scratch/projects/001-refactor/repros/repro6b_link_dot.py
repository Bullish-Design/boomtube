"""H6b: link: '.' -> link_path == project root -> rmtree of project root."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt6b-"))
proj = root/"proj"; proj.mkdir()
(proj/"boomtube.yaml").write_text("version: 1\n", encoding="utf-8")
(proj/"src").mkdir(); (proj/"src"/"main.py").write_text("print('hi')", encoding="utf-8")
(proj/"README.md").write_text("# readme", encoding="utf-8")

# target also resolves inside... use empty target so target == project root too
spec = LinkSpec(link=".", target="", kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
print("BEFORE: project exists:", proj.exists(), "src/main.py:", (proj/"src"/"main.py").exists())
try:
    apply_all(proj, [spec], ctx)
    print("applied without error")
except OSError as e:
    print("OSError during apply:", type(e).__name__, e)
print("AFTER: project root still exists:", proj.exists())
print("AFTER: src/main.py:", (proj/"src"/"main.py").exists())
print("AFTER: README.md:", (proj/"README.md").exists())
shutil.rmtree(root, ignore_errors=True)
