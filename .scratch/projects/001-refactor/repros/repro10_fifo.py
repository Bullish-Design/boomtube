"""E: FIFO at link path -> migrate_file copy2 on FIFO blocks forever (hang)."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil, os, subprocess

root = Path(tempfile.mkdtemp(prefix="bt10-"))
proj = root/"proj"; proj.mkdir()
fifo = proj/".pipe"; os.mkfifo(fifo)
target = root/"tgt"; target.mkdir()
spec_path = root/"boomtube.yaml"
spec_path.write_text(f"version: 1\nlinks:\n  - link: '.pipe'\n    target: '{target}/pipe'\n    kind: auto\n    migrate: true\n")

# kind auto: link exists -> is_dir? no -> 'file' -> migrate_file on a FIFO
import subprocess
p = subprocess.run(["/tmp/btenv/bin/python", "-c", f"""
import sys; sys.path.insert(0, '/home/andrew/Documents/Projects/boomtube/src')
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
from pathlib import Path
proj = Path('{proj}')
spec = LinkSpec(link='.pipe', target='{target}/pipe', kind='auto', migrate=True)
ctx = {{'project_root': str(proj), 'project_name': proj.name}}
apply_all(proj, [spec], ctx)
print('done')
"""], capture_output=True, text=True, timeout=10)
print("FIFO apply: rc=", p.returncode, "stdout:", p.stdout.strip(), "stderr:", p.stderr.strip()[:300])
