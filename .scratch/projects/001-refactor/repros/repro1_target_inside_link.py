"""H1/seed1: link: .notes, target: .notes/backup -> data loss + dangling symlink."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.apply import apply_all
from boomtube.models import LinkSpec

root = Path(tempfile.mkdtemp(prefix="bt1-"))
proj = root / "proj"; proj.mkdir()

# Real dir at link path with user data
link_dir = proj / ".notes"; link_dir.mkdir()
(link_dir / "idea.txt").write_text("my precious notes", encoding="utf-8")
# Pre-existing backup with data too
(link_dir / "backup").mkdir()
(link_dir / "backup" / "old.txt").write_text("old backup data", encoding="utf-8")

spec = LinkSpec(link=".notes", target=".notes/backup", kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}

print("BEFORE: .notes/idea.txt exists:", (link_dir/"idea.txt").exists())
print("BEFORE: .notes/backup/old.txt exists:", (link_dir/"backup"/"old.txt").exists())
apply_all(proj, [spec], ctx)
link = proj/".notes"
print("AFTER: link is symlink:", link.is_symlink())
print("AFTER: symlink target:", link.readlink() if link.is_symlink() else None)
print("AFTER: target dir exists:", (proj/".notes/backup").exists())
print("AFTER: idea.txt exists (via symlink):", (link/"idea.txt").exists())
print("AFTER: old.txt exists (via symlink):", (link/"backup"/"old.txt").exists())
print("DATA LOSS:", not (link/"idea.txt").exists() and not (proj/".notes/backup/idea.txt").exists())
shutil.rmtree(root, ignore_errors=True)
