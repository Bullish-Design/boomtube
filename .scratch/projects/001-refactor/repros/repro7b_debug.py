import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.migrate import _list_files
root = Path(tempfile.mkdtemp(prefix="bt7b-"))
a = root/"a"; b = root/"b"
a.mkdir(); b.mkdir()
(a/"x").write_text("A-file-x"); (a/"z.txt").write_text("z")
(b/"x").mkdir(); (b/"x"/"inner.txt").write_text("B-dir-x")
af, bf = _list_files(a), _list_files(b)
rels = sorted(set(af) | set(bf))
print("a_files:", af)
print("b_files:", bf)
print("sorted all_rels:", rels)
shutil.rmtree(root, ignore_errors=True)
