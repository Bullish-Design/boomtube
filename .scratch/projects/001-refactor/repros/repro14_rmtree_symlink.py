"""B: remove_path(real dir containing symlink to OUTSIDE dir) — must not follow."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.fsops import remove_path
root = Path(tempfile.mkdtemp(prefix="bt14-"))
outside = root/"outside"; outside.mkdir(); (outside/"precious.txt").write_text("KEEP", encoding="utf-8")
victim = root/"victim"; victim.mkdir()
(victim/"f").write_text("x")
(victim/"linkdir").symlink_to(outside, target_is_directory=True)
(victim/"linkfile").symlink_to(outside/"precious.txt")
remove_path(victim)
print("victim removed:", not victim.exists())
print("outside dir intact:", outside.exists())
print("outside/precious.txt intact:", (outside/"precious.txt").read_text(encoding="utf-8") == "KEEP")
shutil.rmtree(root, ignore_errors=True)
