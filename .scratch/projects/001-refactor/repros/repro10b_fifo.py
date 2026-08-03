import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")
from pathlib import Path
import tempfile, shutil, os
root = Path(tempfile.mkdtemp(prefix="bt10b-"))
proj = root/"proj"; proj.mkdir()
fifo = proj/".pipe"; os.mkfifo(fifo)
target = root/"tgt"; target.mkdir()
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
spec = LinkSpec(link='.pipe', target=str(target/'pipe'), kind='auto', migrate=True)
ctx = {'project_root': str(proj), 'project_name': proj.name}
try:
    apply_all(proj, [spec], ctx)
    print("done")
except Exception as e:
    import traceback; traceback.print_exc()
shutil.rmtree(root, ignore_errors=True)
