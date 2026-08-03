"""H3/seed4: link: ../outside escapes project root -> operates outside project."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil
from boomtube.models import LinkSpec

# Show validation accepts it
spec = LinkSpec(link="../outside", target="/somewhere/else", kind="dir", migrate=True)
print("LinkSpec accepted: link=../outside  ->", spec.link)

# Now the destructive part: real dir OUTSIDE project at link path, migrate=True
root = Path(tempfile.mkdtemp(prefix="bt3-"))
proj = root / "proj"; proj.mkdir()
outside = root / "outside"; outside.mkdir()
(outside / "secrets.txt").write_text("precious outside data", encoding="utf-8")

from boomtube.apply import apply_all
spec2 = LinkSpec(link="../outside", target=str(root/"ext"/"mirror"), kind="dir", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
print("BEFORE: outside/secrets.txt:", (outside/"secrets.txt").exists())
apply_all(proj, [spec2], ctx)
print("AFTER: outside is symlink:", outside.is_symlink())
print("AFTER: outside/secrets.txt:", (outside/"secrets.txt").exists())
print("AFTER: mirror/secrets.txt:", (root/"ext"/"mirror"/"secrets.txt").exists())
print("OUTSIDE-PROJECT DATA LOSS:", not (outside/"secrets.txt").exists() and not (root/"ext"/"mirror"/"secrets.txt").exists())
shutil.rmtree(root, ignore_errors=True)
