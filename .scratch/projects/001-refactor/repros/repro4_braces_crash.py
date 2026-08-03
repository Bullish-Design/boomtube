"""H4/seed3: '{}' in var/target escapes except KeyError -> uncaught ValueError."""
import sys
sys.path.insert(0, "/home/andrew/Documents/Projects/boomtube/src")

# Case 1: resolve_vars with '{}' in a var value
from boomtube.resolve import resolve_vars, VarResolutionError
try:
    resolve_vars({"a": "{}"}, {"project_root": "x", "project_name": "y"})
    print("resolve_vars: no error?!")
except VarResolutionError as e:
    print("resolve_vars: clean VarResolutionError:", e)
except ValueError as e:
    print("resolve_vars: UNCAUGHT ValueError escaped:", e)

# Case 2: missing var in target (raw KeyError at apply time)
from boomtube.apply import apply_all
from boomtube.models import LinkSpec
from pathlib import Path
import tempfile, shutil
root = Path(tempfile.mkdtemp(prefix="bt4-"))
proj = root/"proj"; proj.mkdir()
spec = LinkSpec(link=".env", target="{undefined_var}/x.env", kind="file", migrate=True)
ctx = {"project_root": str(proj), "project_name": proj.name}
try:
    apply_all(proj, [spec], ctx)
    print("target missing var: no error?!")
except KeyError as e:
    print("target missing var: UNCAUGHT raw KeyError:", e)
shutil.rmtree(root, ignore_errors=True)

# Case 3: '{' single brace in var
try:
    resolve_vars({"a": "{x"}, {"project_root": "x", "project_name": "y"})
except ValueError as e:
    print("single '{': UNCAUGHT ValueError escaped:", e)
