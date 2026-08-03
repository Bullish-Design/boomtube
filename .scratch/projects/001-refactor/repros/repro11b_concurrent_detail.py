import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil, os, subprocess, traceback

root = Path(tempfile.mkdtemp(prefix="bt11b-"))
proj = root/"proj"; proj.mkdir()
link_dir = proj/".notes"; link_dir.mkdir()
for i in range(300):
    (link_dir/f"f{i}.txt").write_text(f"data {i} " * 10, encoding="utf-8")
target = root/"ext"/"notes"; os.makedirs(target)
for i in range(300):
    (target/f"g{i}.txt").write_text(f"other {i} " * 10, encoding="utf-8")
cfg = root/"boomtube.yaml"
cfg.write_text(f"version: 1\nlinks:\n  - link: '.notes'\n    target: '{target}'\n    kind: dir\n    migrate: true\n")

script = f"""
import sys; sys.path.insert(0, '/home/andrew/Documents/Projects/boomtube/src')
import traceback
from boomtube.apply import apply_all
from boomtube.config import load_config
from boomtube.resolve import build_context
from pathlib import Path
proj = Path('{proj}')
cfg = load_config(Path('{cfg}'))
ctx = build_context(proj, cfg.vars)
try:
    apply_all(proj, cfg.links, ctx)
    print('OK')
except Exception:
    traceback.print_exc()
"""
procs = [subprocess.Popen(["/tmp/btenv/bin/python", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
outs = [p.communicate(timeout=90) for p in procs]
for i,(o,e) in enumerate(outs):
    combined = (o+e).strip()
    print(f"=== proc{i} rc={procs[i].returncode} ===")
    print(combined[:900])
shutil.rmtree(root, ignore_errors=True)
