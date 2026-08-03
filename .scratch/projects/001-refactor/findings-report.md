# Adversarial Review — Boomtube 0.1.0

Reviewer: adversarial senior reviewer (no source files modified)
Scope: all of `src/boomtube/*.py`, all 27 tests (green, then ignored), README, pyproject
Environment: Python 3.13.13, pydantic 2.13.4, typer 0.27.1, PyYAML 6.0.3
All reproductions: `/tmp/btr/repro*.py`, run with `/tmp/btenv/bin/python`.

---

## Findings

### CRITICAL

#### F1 — Target-inside-link-path: migration preserves data, then `rmtree` deletes it (seed 1 — CONFIRMED)
- **Location**: `apply.py:41-91` (`apply_link`), `fsops.py:50` (`remove_path`), `migrate.py:88-138` (merge assumes disjoint trees)
- **Trigger**: `link: .notes`, `target: .notes/backup` (target inside the link's tree), `migrate: true`, real data at link path.
- **Reproduction**: `repro1_target_inside_link.py`
  ```
  BEFORE: .notes/idea.txt exists: True
  BEFORE: .notes/backup/old.txt exists: True
  AFTER: link is symlink: True
  AFTER: symlink target: .../proj/.notes/backup
  AFTER: target dir exists: False
  DATA LOSS: True
  ```
- **Mechanism**: `target_path.mkdir()` creates `.notes/backup` *inside* the real dir being migrated (apply.py:50-51). `migrate_dir(.notes, .notes/backup)` bidirectionally copies the two overlapping trees (both directions succeed — the data looks "preserved"). Then `remove_path(.notes)` → `shutil.rmtree` deletes the entire tree **including the backup that just received the copies**. A dangling symlink `.notes → .notes/backup` is left behind: the user's data is gone and the link resolves to nothing.
- **Impact**: Silent, total destruction of the user's directory and its "migrated" copy. This is the tool's central documented safety promise ("ensuring no data loss") — broken.
- **Fix**: Reject any config where the normalized target lies inside the normalized link tree (or vice-versa) before doing anything; migrate with a staging directory outside both trees.

#### F2 — `migrate: false` silently `rmtree`s a non-empty real directory at the link path (checklist A — CONFIRMED)
- **Location**: `apply.py:89` (`remove_path(link_path)` is unconditional), `fsops.py:44-50`
- **Trigger**: `migrate: false` (which the README documents as the *default*) + any real file/dir at the link path. No warning, no confirmation, no trash.
- **Reproduction**: `repro2_migrate_false_delete.py`
  ```
  BEFORE: diary exists: True
  AFTER: link is symlink: True
  AFTER: diary exists anywhere: False
  DATA LOSS: True
  ```
  A directory containing `diary.txt` and `sub/x.txt` is deleted outright; the target directory ends up **empty**.
- **Impact**: The README presents `migrate: false` as the ordinary no-migration setting ("default: false") and never states that existing data at the link path is destroyed. A user following the README loses data. Violates the README's own "Safety First: Never delete data without migration or explicit user action" — there is no migration and no disclosure.
- **Fix**: When `migrate: false` and the link path is a non-empty real file/dir, refuse (require `--force` or an explicit `migrate: true`), or move data to trash instead of `rmtree`.

#### F3 — `link: ../outside` passes validation and operates outside the project root (seed 4 — CONFIRMED)
- **Location**: `models.py:23-33` (`link_must_be_relative` only rejects absolute, `~`-prefixed, empty), used at `apply.py:41`
- **Trigger**: `link: ../outside` (or `a/../../b`). Validation accepts it ("relative").
- **Reproduction**: `repro3b_link_dotdot_nomigrate.py`
  ```
  AFTER outside/precious.txt exists: False
  AFTER outside is symlink: True
  DATA OUTSIDE PROJECT ROOT DESTROYED: True
  ```
  With `migrate: true` the outside dir is *replaced* by a symlink (`repro3_link_dotdot.py`); with `migrate: false` the outside data is destroyed.
- **Impact**: `rmtree`/`symlink_to`/`mkdir` all run on paths **outside the project root** — including deletion of unrelated user data elsewhere on disk. The validator's "must be relative to project root" comment is false.
- **Fix**: `os.path.commonpath`/`resolve()` check that `project_root / spec.link` stays inside `project_root`.

#### F4 — `link: "."` (or target == link) deletes the entire project root, silently (new attack — CONFIRMED)
- **Location**: `apply.py:41` (`link_path = project_root / spec.link` with `link="."`), `apply.py:89`, `fsops.py:50`
- **Trigger**: `link: "."`, `target: ""` (or `"."`). Both fields pass validation (target has *no* validator; empty `link` is the only rejected value).
- **Reproduction**: `repro6b_link_dot.py`
  ```
  BEFORE: project exists: True src/main.py: True
  applied without error
  AFTER: project root still exists: False
  AFTER: src/main.py: False
  ```
  `migrate_dir(proj, proj)` sees every file on both sides as "identical", so nothing is copied, then `remove_path(proj)` **rmtrees the project root**. The run reports success ("applied without error") and the project root becomes a broken self-referential symlink.
- **Impact**: Complete silent destruction of the project — worst possible outcome, reported as success.
- **Fix**: Validate that `link` and `target` normalize to distinct, non-root paths inside/relative to the project; refuse `link` that resolves to the project root itself; never `rmtree` a path equal to `project_root` (or its ancestors).

### HIGH

#### F5 — `{}` / stray braces raise `ValueError`, escaping every `except KeyError`, crashing the CLI (seed 3 — behavior CONFIRMED, exception type refuted)
- **Location**: `resolve.py:19-20` and `resolve.py:74-75` (`except KeyError` only), `apply.py:42` (no guard at all)
- **Trigger**: any var value or `target` containing `{}`, `{`, or `{x` (valid YAML, plausible typo). Seed said `IndexError` — in Python 3.13 `"{}".format_map({})` raises **`ValueError: Format string contains positional fields`**; `"{"` → `ValueError: Single '{' ...`; `"{x"` → `ValueError: expected '}' ...`.
- **Reproduction**: `repro4_braces_crash.py`; full CLI traceback in the session log:
  ```
  ValueError: Format string contains positional fields
  exit: 1 | exception: ValueError
  ```
- **Impact**: A clean `ConfigError`/`VarResolutionError` (documented, exit 2) is bypassed; the user gets a raw traceback and exit 1.
- **Fix**: Catch `(KeyError, ValueError, IndexError)` around every `format_map` (or pre-validate templates), and wrap `apply.py:42` the same way.

#### F6 — Missing variable in `target` is an unhandled `KeyError` (new attack — CONFIRMED)
- **Location**: `apply.py:42` (`spec.target.format_map(ctx)` — not inside any try/except; the CLI catches only `ConfigError`/`VarResolutionError`/`PermissionError`/`OSError`)
- **Trigger**: `target: "{missing}/x"` with no `missing` var. Config validates fine (`target` is just a string).
- **Reproduction**: `repro4_braces_crash.py` (case 2):
  ```
  target missing var: UNCAUGHT raw KeyError: 'undefined_var'
  ```
  CLI: `exit: 1 | exception: KeyError` with traceback.
- **Impact**: Crash instead of a clean "Missing variable" error; also means `apply` discovers broken templates only at runtime, after partially mutating earlier links.
- **Fix**: Resolve/validate all `target` templates in `load_config` or `build_context`, raising `VarResolutionError`.

#### F7 — Documented `boomtube apply` invocation is broken with current dependency resolution (new attack — CONFIRMED)
- **Location**: `cli.py:14-16` (`app = typer.Typer(...)`, `@app.command()` with `name=None`), `pyproject.toml:11` (`typer>=0.12`, unbounded)
- **Trigger**: any `boomtube apply ...` invocation under typer 0.27.1 (what a fresh `pip install` resolves today).
- **Reproduction**:
  ```
  $ boomtube apply --project-root ... --config ...
  Usage: boomtube [OPTIONS]
  ╭─ Error ────────────────────────────────────╮
  │ Got unexpected extra argument(s) (apply)   │
  ╰────────────────────────────────────────────╯
  exit=2
  ```
  A minimal two-command Typer app works fine; a **single** `@app.command()` app under typer 0.27.1 auto-invokes as the main command, so `apply` becomes an unexpected positional. Even `@app.command(name="apply")` fails identically. Bare `boomtube` (no args) runs apply on the CWD — that is the only working invocation.
- **Impact**: The README's primary usage (`boomtube apply`, `boomtube apply --verbose`) fails on every fresh install with a confusing error, exit 2.
- **Fix**: Pin `typer<0.13` or restructure so the app has an explicit root callback/subcommand layout that works under the supported range.

#### F8 — Kind misdetection crashes mid-operation: `kind: file` on a real dir → `IsADirectoryError`; `kind: dir` on a real file → `FileExistsError` (seed 5 — CONFIRMED)
- **Location**: `apply.py:74-76` (dispatches on possibly-wrong `kind`), `migrate.py:53` (`_copy(a, b)` on a dir), `migrate.py:91` (`a.mkdir` when `a` is a file)
- **Trigger**: explicit `kind` that contradicts reality (or any future misdetection): `kind: file` + real dir at link with `migrate: true`.
- **Reproduction**: `repro5_kind_file_on_dir.py`, `repro12_edgecases.py` (case 3):
  ```
  IsADirectoryError raised (unhandled at library level): [Errno 21] Is a directory: '.../.cfg'
  kind=dir on file -> FileExistsError [Errno 17] File exists: '.../.env'
  ```
  Through the CLI these are caught as `OSError` → exit 4, but nothing was applied and remaining links are skipped (see F12).
- **Impact**: Crash with partial/zero state; no data loss by itself, but if `kind` ever gets misdetected on a `migrate` run, migration is silently skipped and the tool aborts mid-config.
- **Fix**: Sniff the real type at the link path when calling `migrate_*`; make `_copy`/`mkdir` raise a typed error; per-link isolation (F12).

#### F9 — Directory merge type collision (file vs dir at the same relative path) → crash + partial merge + silent file nesting (new attack — CONFIRMED)
- **Location**: `migrate.py:102-110`, `migrate.py:15` (`_ensure_parent`), `migrate.py:19-20` (`copy2`)
- **Trigger**: A has file `x` while B has directory `x/` containing files.
- **Reproduction**: `repro7_type_collision.py` / `repro7c_trace.py`:
  ```
  FileExistsError [Errno 17] File exists: '.../a/x'
  z.txt copied to B (processed before crash?): False
  ```
  Also: `shutil.copy2(file, existing_dir)` **silently nests** the file as `x/x` inside the dir instead of failing (observed) — so a "file beats dir" merge produces a wrong location, not an error.
- **Impact**: Partial migration state (files after the collision are never copied), then crash. In an `apply` run the link stays a real dir — data safe but the merge is half-done and the user is left with an opaque error.
- **Fix**: Detect rel collisions where one side is a directory; error cleanly before mutating, or record the conflict as a conflict file.

### MEDIUM

#### F10 — Conflict files duplicate and spread across runs on repeated migration (CONFIRMED)
- **Location**: `migrate.py:130-138` (conflict naming/suffix), `util.py:11-21`
- **Trigger**: `migrate_dir`/`migrate_file` run twice on the same pair after a tie-conflict (or through any caller that migrates the same two real dirs repeatedly).
- **Reproduction**: `repro9b_conflict_spread.py`
  ```
  run1: conflicts=1
  run2: copied_b_to_a=1, conflicts=1
  conflict files in A after run2: ['f.conflict-from-project-20260803-150119']
  conflict files in B after run2: ['f.conflict-from-project-...', 'f.conflict-from-project-...-1']
  ```
- **Impact**: README claims conflicts are "preserved as separate files" at the target — on re-runs a second duplicate appears at B and the prior conflict is copied back into A. Through the normal `apply` flow migration runs only once (the link becomes a symlink), so impact is limited; still a violation of the documented conflict semantics and of migration idempotency.
- **Fix**: Exclude `.conflict-from-project-*` files from `_list_files` (or record them in stats) so they are never re-merged; make the conflict name deterministic per content.

#### F11 — TOCTOU: file removed between `exists()` and `stat()`/hash → unhandled `FileNotFoundError` (seed 6 — CONFIRMED)
- **Location**: `migrate.py:45-48` (`exists()`), `migrate.py:60-66` / `hashing.py:9-14` (stat + `open`), `migrate.py:120` (`ap.stat()`)
- **Trigger**: any concurrent modification/deletion during a migration; demonstrated deterministically by interposing on `files_identical`.
- **Reproduction**: `repro13_toctou.py`
  ```
  TOCTOU crash: FileNotFoundError -> [Errno 2] No such file or directory: '.../a/f'
  ```
- **Impact**: Crash (exit 4) with partial state; no data loss by itself, but the same race is what the concurrent-applies test hit (F14). No retry, no skippable-error handling.
- **Fix**: Catch `FileNotFoundError` around stat/hash/copy per file and skip/requeue that file; or stat once via `os.lstat` and copy from the open fd.

#### F12 — `apply_all` aborts at the first failing link; no per-link error reporting (CONFIRMED)
- **Location**: `apply.py:94-96` (no try/except around `apply_link`)
- **Reproduction**: `repro15_abort.py`
  ```
  apply_all aborted at first failing link: FileExistsError
  .good link created (would be if continued): False
  ```
- **Impact**: A single bad link (any of F5-F9) prevents all remaining links from being applied, and the CLI gives no summary of what succeeded before the abort.
- **Fix**: Catch per-link errors, log the failing link, continue, and report a non-zero exit with a summary.

#### F13 — Empty `target` is accepted and creates a self-referential symlink (CONFIRMED)
- **Location**: `models.py` (`target` has no validator), `fsops.py:26-35` (`Path("")` → `.` → project root), `apply.py:43`
- **Reproduction**: `repro6_empty_target.py`
  ```
  link is symlink: True
  symlink target: .../proj
  target == project root: True
  ```
- **Impact**: `.notes` points at the whole project — recursive-walk loops for any tool that follows symlinks (backups, `find`, `tar`), and with a real dir at the link + `migrate: true` the whole project gets copied into `.notes` before the `rmtree`. No data loss in the tested flow, but a foot-gun with no validation gate.
- **Fix**: Reject empty `target` (and `target` resolving to the project root or the link path) at validation.

#### F14 — Concurrent `apply` runs race: one wins, the other crashes mid-migration (checklist E — CONFIRMED)
- **Location**: `migrate.py:120` (`ap.stat()` on a tree another process just removed), `apply.py:89` (`remove_path` vs in-flight migration)
- **Reproduction**: `repro11b_concurrent_detail.py`
  ```
  proc0: OK
  proc1: FileNotFoundError: ... '.../proj/.notes/f123.txt'
  final: link is symlink: True | target f0 exists: True | g0 exists: True
  ```
- **Impact**: In the tested case no data was lost (one process crashed; the winner completed cleanly). But there is no locking, so the loser aborts (F11/F12) and a different interleaving (e.g., `remove_path` racing another process's migration copy) could leave a dangling link or partial tree. Rate MEDIUM because the observed worst case is a crash, not corruption.
- **Fix**: File-lock around `apply` (e.g., `flock` on the project), or tolerate/staleness-check.

### LOW / INFO

#### F15 — No post-copy verification before the source is deleted (structural risk — UNVERIFIED as data loss)
- **Location**: `migrate.py:19-20` (`copy2`), `apply.py:89` (`remove_path`)
- **Trigger**: disk-full / I/O error mid-`copy2` producing a truncated destination.
- **Impact**: The source is deleted after an unverified copy; a truncated destination would then be the only copy. I could not reproduce disk-full cheaply; the structure (copy → delete with no size check) makes this a real residual risk. Marked `UNVERIFIED` per the rules.
- **Fix**: Verify `dst.stat().st_size == src.stat().st_size` (or checksum) before `remove_path`.

#### F16 — User vars can override the `project_root`/`project_name` builtins (CONFIRMED)
- **Location**: `resolve.py:27-31` (`{**builtins, **resolved_user}` — user wins)
- **Reproduction**:
  ```
  ctx['project_root'] = EVIL    # user's var shadows the builtin
  ```
- **Impact**: A `vars: {project_root: ...}` typo silently rewrites every `{project_root}` target. Low likelihood, confusing when it happens.
- **Fix**: Merge builtins last, or reject user vars named `project_root`/`project_name`.

#### F17 — README says `migrate` defaults to `false`; code defaults to `true` (seed 2 — CONFIRMED)
- **Location**: README lines 116, 158 vs `models.py:19` (`migrate: bool = True`)
- **Impact**: Users following the README believe migration (and its F1/F13 hazards) won't run when `migrate` is omitted — it will. Also the README's "default false" is what sends users toward the dangerous F2 configuration.

#### F18 — README documents a `boomtube config` command; the CLI has no such command (CONFIRMED)
- **Location**: README lines 94-97, 192-204; `cli.py` registers only `apply`.

#### F19 — README documents exit code 1 for failures; the CLI uses 2 (config/resolution), 3 (permission), 4 (OS error) (CONFIRMED)
- **Location**: README "Exit Codes" vs `cli.py:45-58`. Verified: config error → 2, OSError → 4, success → 0.

#### F20 — FIFO at the link path → `SpecialFileError` crash (CONFIRMED, no hang)
- **Location**: `migrate.py:53` (`_copy` of a FIFO), `detect_kind` classifies it as `file`
- **Reproduction**: `repro10b_fifo.py` → `shutil.SpecialFileError: '.../.pipe' is a named pipe` (OSError subclass → exit 4). No data loss; the FIFO is left in place. Special files *inside* walked dirs are correctly filtered by `_list_files` (checked).

#### F21 — `migrate_file` treats a broken symlink as "missing" and writes *through* it to its target (seed 9 — apply path SAFE, direct API surprising)
- **Location**: `migrate.py:41-49` (guards use `exists()`; a broken symlink is `exists()==False`)
- **Reproduction**: `repro8_symlink_safety.py` (seed9b)
  ```
  migrate_file(broken-symlink-A, B) -> copied_b_to_a=1
  ghost-target file created at symlink target: True  content: hello
  ```
- **Impact**: If the link path were a broken symlink and something called `migrate_file` on it, content is written to *whatever the symlink points to* (possibly outside the project) and it is reported as "copied to A". In the real `apply` flow a broken symlink is routed to the `is_symlink` branch and replaced correctly (verified — seed 9 at apply level is safe). LOW.

#### F22 — Sub-millisecond mtime differences produce spurious conflict files (INFO)
- **Location**: `migrate.py:11` (`_MTIME_EPS = 1e-3`), `migrate.py:71-76, 123-128`
- **Reproduction**: `repro12_edgecases.py` — 0.5 ms apart, different content → conflict file. Direction logic itself is correct in all tested mtime orderings (edit-B-rerun copied the right way), so this only adds noise, never wrong direction.
- **Impact**: None beyond extra conflict files on 1-second-granularity filesystems or sub-ms timestamps. Matches the code's documented design.

#### F23 — README says var resolution is a "topological sort"; the code uses DFS memoization (INFO)
- Equivalent output; no action needed.

#### F24 — `version: yes` accepted as version 1 (PyYAML 1.1 bool → int coercion) (INFO)

---

## Confirmed refutations (seeds that are NOT bugs)

- **Seed 7 (second-run idempotency)**: CONFIRMED SAFE. Two `apply` runs on a migrated setup: same symlink inode, migration results intact, target content preserved (`repro9_idempotency.py`).
- **Seed 8 (`remove_path` on symlink-to-dir)**: CONFIRMED SAFE. `is_symlink()` branch → `unlink`, target directory survives (`repro8_symlink_safety.py`).
- **Seed 9 (broken symlink at link path)**: CONFIRMED SAFE at the apply level — routed through the `is_symlink()` branch and replaced correctly. (Direct `migrate_file` writes through it — F21, LOW.)
- **Seed 3 exception type**: the *behavior* (unhandled crash) is real, but it's `ValueError`, not `IndexError` (F5).
- **mtime "newer wins" direction**: no wrong-direction copy observed in any ordering tested, including after `copy2`-preserved mtimes (F22).

---

## Summary

### Highest-severity bugs, ranked by user impact

1. **F1** target-inside-link (`link: .notes`, `target: .notes/backup`) — data loss + dangling symlink, with `migrate: true` (the *default*).
2. **F4** `link: "."` / target == link — the **entire project root is deleted, reported as success**.
3. **F3** `link: ../outside` — escape from the project root; data *outside* the project can be destroyed.
4. **F2** `migrate: false` (README-documented default) + non-empty real dir at link — silent `rmtree` of user data.
5. **F7** the documented `boomtube apply` CLI invocation is broken under current dependency resolution (typer 0.27.1) — the whole tool is unusable as documented on a fresh install.
6. **F5/F6** unhandled `ValueError`/`KeyError` crashes instead of clean errors.
7. **F8/F9** kind/type mismatches crash mid-migration with partial state.
8. **F11/F12/F14** TOCTOU + per-link abort + concurrency races.

### Per-module risk rating (one line each)

| Module | Rating |
|---|---|
| `apply.py` | **CRITICAL** — unconditional `remove_path` after an unvalidated merge; no target/link overlap checks; unguarded `format_map`. |
| `migrate.py` | **CRITICAL** — merge assumes disjoint trees; type collisions crash with partial state; TOCTOU; conflict files duplicate/spread. |
| `fsops.py` | **HIGH** — `rmtree` is the data-loss primitive and is reached on F1/F2/F3/F4 paths; `remove_path` itself is fine. |
| `models.py` | **HIGH** — `..` escapes pass "relative" validation; `target` has zero validation; `migrate` default contradicts README. |
| `resolve.py` | **MEDIUM** — `except KeyError` misses `ValueError`; user vars override builtins. |
| `cli.py` | **MEDIUM** — broken with modern typer; exit codes don't match README; `config` command missing. |
| `util.py` / `hashing.py` | **LOW** — unique-path and hashing logic sound; hashing has no TOCTOU guard. |

### README claims the code does not deliver

- `migrate` default is documented as `false`; the code defaults to `true` (F17).
- A `boomtube config` command is documented but does not exist (F18).
- Exit code `1` is documented for failures; the CLI emits 2/3/4 (F19).
- "ensuring no data loss through intelligent conflict resolution" is false for F1-F4.
- "Never delete data without migration or explicit user action" is violated by F2 (deletion with neither).
- "Conflict Preservation: original file remains unchanged at the target location" — holds for a single run, violated on re-runs (F10).
- "Idempotent Operations: Safe to run multiple times without side effects" — holds for `apply` (verified), not for repeated migration of a real-dir pair (F10).
- Variable resolution is described as a "topological sort" — actually DFS memoization (F23, cosmetic).
