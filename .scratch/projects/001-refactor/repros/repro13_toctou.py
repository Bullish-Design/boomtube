"""Seed6: file removed between exists() check and sha256/stat -> unhandled crash."""
import sys, os
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
import boomtube.migrate as M
from boomtube.migrate import migrate_dir

root = Path(tempfile.mkdtemp(prefix="bt13-"))
a = root/"a"; b = root/"b"; a.mkdir(); b.mkdir()
(a/"f").write_text("AAAA"); (b/"f").write_text("BBBB")

# Interpose: delete A's file right before the content hash runs (simulates concurrent edit)
orig = M.files_identical
def sneaky(x, y):
    if (a/"f").exists() and not getattr(sneaky, "done", False):
        sneaky.done = True
        (a/"f").unlink()   # TOCTOU window: vanishes after exists() check, before hash
    return orig(x, y)
M.files_identical = sneaky

try:
    migrate_dir(a, b)
    print("no crash?!")
except FileNotFoundError as e:
    print("TOCTOU crash: FileNotFoundError ->", e)
except OSError as e:
    print("TOCTOU crash:", type(e).__name__, e)
print("state: b/f intact:", (b/"f").read_text(encoding="utf-8") == "BBBB")
shutil.rmtree(root, ignore_errors=True)
