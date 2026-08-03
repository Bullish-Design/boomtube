"""E: two concurrent applies against same config — race reproduction."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil, os, subprocess

root = Path(tempfile.mkdtemp(prefix="bt11-"))
proj = root/"proj"; proj.mkdir()
link_dir = proj/".notes"; link_dir.mkdir()
for i in range(200):
    (link_dir/f"f{i}.txt").write_text(f"data {i} " * 10, encoding="utf-8")
target = root/"ext"/"notes"
os.makedirs(target)
for i in range(200):
    (target/f"g{i}.txt").write_text(f"other {i} " * 10, encoding="utf-8")

cfg = root/"boomtube.yaml"
cfg.write_text(f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{target}'\n    kind: dir\n    migrate: true\n")

script = """
import sys; sys.path.insert(0, '/home/andrew/Documents/Projects/boomtube/src')
from boomtube.apply import apply_all
from boomtube.config import load_config
from boomtube.resolve import build_context
from pathlib import Path
proj = Path('%s')
cfg = load_config(Path('%s'))
ctx = build_context(proj, cfg.vars)
apply_all(proj, cfg.links, ctx)
print('OK')
""" % (proj, cfg)

procs = [subprocess.Popen(["/tmp/btenv/bin/python", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
outs = [p.communicate(timeout=60) for p in procs]
for i,(o,e) in enumerate(outs):
    print(f"proc{i}: rc={procs[i].returncode} out={o.strip()[:80]!r} err={e.strip()[:200]!r}")
# Final state: is the link a symlink, and is data intact?
link = proj/".notes"
print("final: link is symlink:", link.is_symlink())
print("final: target f0 exists:", (target/"f0.txt").exists(), "| g0 exists:", (target/"g0.txt").exists())
print("final: via link f0 exists:", (link/"f0.txt").exists())
shutil.rmtree(root, ignore_errors=True)
