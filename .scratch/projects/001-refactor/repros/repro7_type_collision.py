"""H8: migrate_dir type collision — A has file 'x', B has dir 'x/' -> IsADirectoryError, partial state."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.migrate import migrate_dir

root = Path(tempfile.mkdtemp(prefix="bt7-"))
a = root/"a"; b = root/"b"
a.mkdir(); b.mkdir()
(a/"x").write_text("A-file-x", encoding="utf-8")
(a/"z.txt").write_text("after-x-in-sorted-order", encoding="utf-8")  # sorts AFTER 'x'
(b/"x").mkdir(); (b/"x"/"inner.txt").write_text("B-dir-x", encoding="utf-8")

try:
    st = migrate_dir(a, b)
    print("no error, stats:", st)
except OSError as e:
    print("OSError:", type(e).__name__, e)
# partial state: was z.txt copied before the crash?
print("z.txt copied to B (processed before crash?):", (b/"z.txt").exists())
print("A/x still original:", (a/"x").read_text(encoding="utf-8") == "A-file-x")
print("B/x still a dir with inner.txt:", (b/"x"/"inner.txt").exists())
shutil.rmtree(root, ignore_errors=True)
