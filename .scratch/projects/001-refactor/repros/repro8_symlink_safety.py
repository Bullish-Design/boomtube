"""H9: seed8 (symlink-to-dir via remove_path) + seed9 (broken symlink branches) + dangling-link check."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.fsops import remove_path

root = Path(tempfile.mkdtemp(prefix="bt8-"))

# seed 8: remove_path on symlink whose target is a directory
realdir = root/"realdir"; realdir.mkdir()
(realdir/"data.txt").write_text("do not delete", encoding="utf-8")
ln = root/"ln"; ln.symlink_to(realdir, target_is_directory=True)
remove_path(ln)
print("seed8: symlink removed:", not ln.exists() and not ln.is_symlink())
print("seed8: target dir survives:", realdir.exists() and (realdir/"data.txt").read_text(encoding="utf-8")=="do not delete")

# seed 9: broken symlink at link path — trace apply's branch
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
proj = root/"proj"; proj.mkdir()
broken = proj/"broken"; broken.symlink_to(root/"nonexistent-target")
target = root/"tgt"; (target).mkdir()
spec = LinkSpec(link="broken", target=str(target), kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
apply_all(proj, [spec], ctx)
print("seed9: broken symlink at link path -> apply replaced it:", broken.is_symlink() and broken.resolve() == target.resolve())

# seed9b: migrate_file called directly on broken-symlink A (copy over symlink target)
from boomtube.migrate import migrate_file
proj2 = root/"proj2"; proj2.mkdir()
bl = proj2/"bl"; bl.symlink_to(root/"ghost-target")
tgt2 = root/"tgt2"; tgt2.write_text("hello", encoding="utf-8")
try:
    st = migrate_file(bl, tgt2)
    print("seed9b: migrate_file(broken-symlink-A, B) ->", st)
    print("seed9b: ghost-target file created at symlink target:", (root/"ghost-target").exists(), "content:", (root/"ghost-target").read_text(encoding="utf-8") if (root/"ghost-target").exists() else None)
    print("seed9b: A still a symlink:", bl.is_symlink())
except OSError as e:
    print("seed9b: OSError:", type(e).__name__, e)
shutil.rmtree(root, ignore_errors=True)
