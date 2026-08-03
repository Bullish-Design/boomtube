"""H3b: link: ../outside + migrate:false -> rmtree OUTSIDE project root, no backup."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt3b-"))
proj = root / "proj"; proj.mkdir()
outside = root / "outside"; outside.mkdir()
(outside / "precious.txt").write_text("OUTSIDE-PROJECT USER DATA", encoding="utf-8")

spec = LinkSpec(link="../outside", target=str(root/"ext"/"mirror"), kind="dir", migrate=False)
ctx = {"project_root": str(proj), "project_name": proj.name}
apply_all(proj, [spec], ctx)
print("BEFORE was True; AFTER outside/precious.txt exists:", (outside/"precious.txt").exists())
print("AFTER outside is symlink:", outside.is_symlink())
print("AFTER ext/mirror/precious.txt exists:", (root/"ext"/"mirror"/"precious.txt").exists())
print("DATA OUTSIDE PROJECT ROOT DESTROYED:", not (outside/"precious.txt").exists() and not (root/"ext"/"mirror"/"precious.txt").exists())
shutil.rmtree(root, ignore_errors=True)
