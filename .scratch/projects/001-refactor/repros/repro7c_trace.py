import sys, traceback
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.migrate import migrate_dir
root = Path(tempfile.mkdtemp(prefix="bt7c-"))
a = root/"a"; b = root/"b"
a.mkdir(); b.mkdir()
(a/"x").write_text("A-file-x"); (a/"z.txt").write_text("z")
(b/"x").mkdir(); (b/"x"/"inner.txt").write_text("B-dir-x")
try:
    migrate_dir(a, b)
except OSError:
    traceback.print_exc()
shutil.rmtree(root, ignore_errors=True)
