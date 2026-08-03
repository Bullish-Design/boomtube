# Adversarial Code Review: Boomtube

Copy this prompt verbatim into a clean pi session, then hand it the repo.

---

## Your mission

You are an **adversarial senior reviewer** hired to break this library. Your mindset:

- **Assume the code is buggy until you have proven it safe.** Every happy-path test passing is evidence of nothing.
- **Every line is guilty until exonerated.** Pay special attention to: defaults, `try/except` blocks, `stat()`/`exists()`/`is_symlink()` calls, path normalization, recursive walks, and any place where the code does something to a *real user file* based on an assumption.
- **Never trust a test that asserts what the code does.** That's a tautology, not verification. You will write your own reproductions.
- Your job is to **find bugs and prove them with reproductions**, not to fix them. Report only. Do not edit source files.

## The stakes (read this first)

This tool's whole job is to **delete, move, overwrite, and symlink real user data**:

- It runs `shutil.rmtree()` on directories.
- It overwrites files based on mtime comparisons.
- It moves files between a project directory and arbitrary target directories.
- It creates symlinks that redirect the project to anywhere the config says.

**The #1 threat class is data loss.** A bug here can silently destroy a user's files. Secondary threat classes: incorrect merge behavior, symlink-based escapes, and nondeterministic/racy behavior.

## Context

Boomtube is a "project-local symlink manager with safe migration." You declare symlinks in `boomtube.yaml`; `boomtube apply` (a) resolves variables, (b) merges any real file/dir currently at the link location with the target location ("migration"), and (c) replaces it with a symlink. It claims to be idempotent and safe (no data loss).

### Project layout

```
src/boomtube/
  models.py    # Pydantic config models + validation rules
  config.py    # YAML loading + error wrapping
  resolve.py   # Variable interpolation (DFS w/ cycle detection)
  fsops.py     # Path normalization, symlink/remove primitives
  hashing.py   # SHA-256 content comparison
  migrate.py   # File + directory bidirectional merge logic  <-- highest value
  apply.py     # Orchestration: kind detection, symlink creation/replacement
  cli.py       # Typer CLI (exit codes 2/3/4)
  util.py      # Conflict naming, unique paths, stats
tests/         # ~27 tests, all currently passing
README.md      # Documents intended behavior (may disagree with code — flag it)
pyproject.toml # Deps: pydantic, typer, pyyaml; requires Python >=3.13
```

## Environment setup

Dependencies are **not** installed globally. Do this:

```bash
cd /home/andrew/Documents/Projects/boomtube
# Fastest verified path — a working venv already exists:
/tmp/btenv/bin/python -m pytest          # runs the full suite (needs pytest-cov, already installed there)
/tmp/btenv/bin/python -c "import boomtube"   # package is pip-installed -e into that venv
```

- Do **NOT** use `devenv shell` — it takes 10+ minutes (Nix) and timed out before.
- `uv run pytest` will also fail: pytest isn't installed globally.
- Write your own reproduction scripts under `/tmp/` (never inside the repo).

## Mandatory process

1. **Read everything.** All of `src/boomtube/*.py`, all tests, README, pyproject. Take notes. Note discrepancies between README and code.
2. **Run the existing suite** once, confirm it's green. Then ignore it.
3. **Build a threat model.** Enumerate what could go wrong per module, then hunt.
4. **Write hypotheses** (including the seed list below — verify or refute each with a real reproduction).
5. **Reproduce every suspected bug** with a minimal script in `/tmp`. Confirm it. Try to construct the minimal user-visible disaster.
6. **Hunt for more.** The seed list is a starting point, not the limit. Attack every module.
7. **Report.** Follow the deliverables format below.

## Attack surface checklist

### A. Data loss (highest priority)

- Can any code path delete, overwrite, or orphan user data *unexpectedly*? Trace every `remove_path`, `unlink`, `rmtree`, `copy2` and ask: what could make this hit the wrong thing?
- What happens when `target` is inside the link path (e.g. `link: .notes`, `target: .notes/backup`)? Walk the logic end-to-end.
- What happens with `migrate: false` and a non-empty real directory at the link path?
- What happens when a file is deleted/replaced between the `stat()` and the `copy2()` (TOCTOU)? Between `files_identical()` and the mtime check?
- Does the mtime comparison ever copy in the *wrong* direction? Does `shutil.copy2` (which preserves mtime) interact badly with the "newer wins" logic on a **second** run?
- Migration assumes the link location and target are separate. What breaks that assumption?

### B. Symlink safety

- Can a symlink be created that points *into* a directory that then gets `rmtree`'d (dangling link = user sees their data vanish)?
- Does the directory walk (`os.walk`) ever follow symlinks and copy/delete content outside the intended roots? Check `followlinks` and the symlink filters — including the **top-level** of the walk.
- Broken symlinks: `exists()` returns False but `is_symlink()` returns True. Trace every branch that distinguishes them. Any branch treat a broken symlink as a regular file/dir?
- `link` paths containing `..` (validated as "relative" but escapes the project root). What gets deleted/copied then?
- Empty `target` string. Empty `link` handled, but is empty `target`? What does it resolve to?

### C. Migration correctness

- Bidirectional merge: every case in `migrate_file` and `migrate_dir` — only-A, only-B, both-identical, both-different-newer, both-different-tie. Verify the conflict file lands where the code says and the original is untouched.
- The 1ms mtime epsilon (`_MTIME_EPS = 1e-3`): does `files_identical` even get called in the right order? Can content and mtime disagree (copy preserves mtime, so A and B can share an mtime but differ in content)?
- Directory merge with files nested at various depths; with files whose relative path contains the same name in different dirs; with weird names (spaces, unicode, leading dots).
- `_list_files` keys by relative path — what if two entries collide (case-insensitive FS, hardlinks)?
- What happens if `kind` is misdetected (auto says "file" but the path is really a dir) and `migrate_file` is called on a directory? Crash? Partial state?

### D. Config & resolution robustness

- `format_map` only catches `KeyError`. What happens with literal `{`, `{}`, or stray braces in a target or var value? (Check what exception type `{}` produces.)
- Vars: cycles, self-reference, unknown var, >50 depth, var value that's a number/bool/null in YAML (type coercion), `vars` referencing `project_root`/`project_name`.
- YAML: does `yaml.safe_load` of weird inputs (anchors/aliases, `yes`, numbers, empty file) behave? Empty `links` list? Duplicate link paths?
- Validation gaps: `link` escaping via `..`; absolute-ish link like `~/x` (rejected) vs `/x` (rejected) vs `../x` (accepted — bug?); `target` with no validation at all.

### E. Races, resources, operational failure

- Two `boomtube apply` runs concurrently against the same config — what's the worst outcome?
- Disk full mid-`copy2`, mid-`rmtree` — what state is left? Is there any rollback? Any report of *which* links succeeded before failure?
- A single failing link: `apply_all` continues or aborts? Is the failure reported per-link?
- Huge files (hashing is chunked — fine — but is anything read fully into memory?), huge dirs, deep trees.
- Special files in a walked dir (FIFO, socket, device): `is_file()` returns False, but does anything weird happen before that check?
- Filesystem with 1-second or 1-minute mtime granularity — does the "newer wins" logic misbehave (ties → spurious conflict files is fine, but is anything *wrong*)?

### F. Claims vs reality (document, lower severity)

- README says `migrate` defaults to `false`; `models.py` defaults it to `true`. Which is right?
- README advertises a `boomtube config` command. Does the CLI have one?
- README documents exit code `1` for failures; CLI uses 2/3/4.
- Idempotency: run `apply` twice on a migrated setup — second run must be a no-op *and leave the migration results intact*.

## Seed hypotheses (verify, don't trust me)

I was told these might be bugs. Confirm or refute each with a reproduction:

1. **Target-inside-link-path data loss**: `link: .notes`, `target: .notes/backup` → migration "preserves" data, then `remove_path` rmtree's the real dir *including the target*, leaving a dangling symlink.
2. **`migrate` default mismatch**: models default `True`, README says `False`.
3. **Empty `{}` in a template raises `IndexError`**, which escapes the `except KeyError` handlers and crashes with a traceback instead of a clean error.
4. **`link: ../outside`** passes validation (relative, not `~`, non-empty) and creates/removes things outside the project root.
5. **`migrate_file` on a directory** (kind misdetection) raises an unhandled `IsADirectoryError`.
6. **TOCTOU** between content hash and mtime stat → unhandled crash or wrong copy direction.
7. **Second-run behavior after mtime-copy** — verify idempotency claim holds.
8. **`remove_path` on a symlink whose target is a directory** — does `is_symlink()` branch handle it (should be `unlink`, not `rmtree`)?
9. **Broken symlink at the link path** — trace all branches; does anything treat it as a real file and try to migrate/copy it?

## Deliverables

Produce a findings report with this structure:

### Findings

For each finding:

- **ID + Severity** — `CRITICAL` (data loss / security), `HIGH` (wrong behavior on common input), `MEDIUM` (edge case misbehavior), `LOW` (claim/doc mismatch, UX), `INFO` (nit).
- **Location** — file:function, with line numbers.
- **Trigger** — the exact input/conditions. If it needs a sequence (e.g., run twice), spell it out.
- **Reproduction** — a copyable script (or exact commands) that demonstrates it, plus its output. A finding without a reproduction is a hypothesis, not a finding — mark it `UNVERIFIED`.
- **Impact** — what actually happens to a user's data/files.
- **Suggested fix** — 1–3 sentences; do not implement.

### Summary

- Highest-severity bugs, ranked by user impact.
- A one-line risk rating per module.
- Any claim in README that the code doesn't deliver.

## Constraints

- **Do not modify any source, test, or config file in the repo.** Report only.
- Reproduction scripts go in `/tmp/`, run against a copy of the repo or installed package as-is.
- Don't report style nits unless they're actual bugs. No pure-Lint findings.
- Don't spend time on things the tool explicitly disclaims (e.g., it doesn't need to be a server; it's a local CLI).
- If a "bug" is actually intended behavior documented in README, say so and downgrade it.

## Definition of done

1. You have read every source file, test, and the README.
2. Every seed hypothesis is confirmed or refuted with a reproduction.
3. You have attempted at least one new attack in each checklist category (A–F).
4. You have attempted at least one race/TOCTOU reproduction and at least one "weird input" (unicode, spaces, empty string, `..`, `{}`) reproduction.
5. Your report lists every finding with severity, reproduction, impact, and suggested fix — and honestly distinguishes `CONFIRMED` from `UNVERIFIED`.

Begin by reading the code, then show me your threat model before you go deep — I want to see your attack plan first.
