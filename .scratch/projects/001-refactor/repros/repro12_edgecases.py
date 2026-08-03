import sys, os
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.migrate import migrate_dir, migrate_file
root = Path(tempfile.mkdtemp(prefix="bt12-"))

# 1) mtime epsilon: files differ in content, mtimes differ by 0.5ms -> tie? conflict?
a = root/"e1a"; b = root/"e1b"; a.mkdir(); b.mkdir()
(a/"f").write_text("AAA"); (b/"f").write_text("BBB")
os.utime(a/"f", (1000.0000, 1000.0000)); os.utime(b/"f", (1000.0005, 1000.0005))
st = migrate_dir(a, b)
print("eps0.5ms ->", st, "| b/f content:", (b/"f").read_text(encoding="utf-8"))

# 2) weird names: spaces, unicode, leading dots
a = root/"e2a"; b = root/"e2b"; a.mkdir(); b.mkdir()
(a/"my file ü.txt").write_text("space")
(a/".hidden").write_text("dot")
(a/"日本語/ファイル.txt").parent.mkdir(); (a/"日本語/ファイル.txt").write_text("jp")
(b/"my file ü.txt").write_text("space")
st = migrate_dir(a, b)
print("weird names ->", st, "| b has:", sorted(str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()))

# 3) kind=dir with real FILE at link
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
proj = root/"proj"; proj.mkdir()
(proj/".env").write_text("KEY=val")
spec = LinkSpec(link=".env", target=str(root/"ext"/"env"), kind="dir", migrate=True)
try:
    apply_all(proj, [spec], ctx={"project_root": str(proj), "project_name": proj.name})
    print("kind=dir on file: no error?!")
except OSError as e:
    print("kind=dir on file ->", type(e).__name__, e)
print("  state: .env still real file:", (proj/".env").is_file(), "| symlink:", (proj/".env").is_symlink())

# 4) hardlinks: same inode on both sides of a file migration
x = root/"x"; y = root/"y"
x.write_text("shared content")
os.link(x, y)
st = migrate_file(x, y)
print("hardlinked same file ->", st)

# 5) second run mtime direction: after copy2, both same mtime; modify B -> B newer -> copies to A?
a = root/"e5a"; b = root/"e5b"; a.mkdir(); b.mkdir()
(a/"f").write_text("v1"); (b/"f").write_text("v1")
os.utime(a/"f", (1000, 1000)); os.utime(b/"f", (900, 900))
st1 = migrate_dir(a, b)
os.utime(b/"f", (3000, 3000))
(b/"f").write_text("v2")
st2 = migrate_dir(a, b)
print("edit-B rerun ->", st2, "| a/f now:", (a/"f").read_text(encoding="utf-8"))
shutil.rmtree(root, ignore_errors=True)
