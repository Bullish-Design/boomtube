"""H5/seed5: kind:file + real dir at link -> IsADirectoryError, partial state."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt5-"))
proj = root/"proj"; proj.mkdir()
link_dir = proj / ".cfg"; link_dir.mkdir()
(link_dir/"data.txt").write_text("real data in a dir", encoding="utf-8")

spec = LinkSpec(link=".cfg", target=str(root/"ext"/"cfg"), kind="file", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
try:
    apply_all(proj, [spec], ctx)
    print("no error?!")
except IsADirectoryError as e:
    print("IsADirectoryError raised (unhandled at library level):", e)
except OSError as e:
    print("OSError:", type(e).__name__, e)
print("state after failure: link is symlink:", (proj/'.cfg').is_symlink())
print("state after failure: real dir still there:", (proj/'.cfg/data.txt').exists())
shutil.rmtree(root, ignore_errors=True)
