"""Conflict file spreads B->A on second migration run (claim: 'preserved on target')."""
import sys, os
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.migrate import migrate_dir
root = Path(tempfile.mkdtemp(prefix="bt9b-"))
a = root/"a"; b = root/"b"; a.mkdir(); b.mkdir()
(a/"f").write_text("aaa"); (b/"f").write_text("bbb")
os.utime(a/"f", (1000,1000)); os.utime(b/"f", (1000,1000))
print("run1:", migrate_dir(a, b))
print("run2:", migrate_dir(a, b))
confA = list(a.glob("f.conflict-from-project-*"))
confB = list(b.glob("f.conflict-from-project-*"))
print("conflict files in A after run2:", [c.name for c in confA])
print("conflict files in B after run2:", [c.name for c in confB])
print("b/f unchanged:", (b/"f").read_text(encoding="utf-8") == "bbb")
shutil.rmtree(root, ignore_errors=True)
