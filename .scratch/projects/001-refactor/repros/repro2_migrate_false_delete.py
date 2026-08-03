"""H2: migrate:false + non-empty real dir at link -> silent rmtree of user data."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt2-"))
proj = root / "proj"; proj.mkdir()
link_dir = proj / ".notes"; link_dir.mkdir()
(link_dir / "diary.txt").write_text("10 years of journals", encoding="utf-8")
(link_dir / "sub").mkdir(); (link_dir / "sub" / "x.txt").write_text("x", encoding="utf-8")

spec = LinkSpec(link=".notes", target=str(root/"ext"/"notes"), kind="dir", migrate=False)
ctx = {"project_root": str(proj), "project_name": proj.name}

print("BEFORE: diary exists:", (link_dir/"diary.txt").exists())
apply_all(proj, [spec], ctx)
link = proj/".notes"
print("AFTER: link is symlink:", link.is_symlink())
print("AFTER: diary exists anywhere:", (proj/".notes/diary.txt").exists() or (root/"ext/notes/diary.txt").exists())
print("AFTER: ext/notes exists:", (root/"ext/notes").exists())
print("DATA LOSS:", not (root/"ext"/"notes"/"diary.txt").exists())
shutil.rmtree(root, ignore_errors=True)
