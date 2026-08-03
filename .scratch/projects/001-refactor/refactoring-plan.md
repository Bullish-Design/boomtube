# Boomtube Refactoring Plan (v2)

Status: planning only — no source/test/config file was modified.
Author: senior engineer (planning session)
Inputs consumed: all `src/boomtube/*.py`, all `tests/*.py`, `README.md`, `pyproject.toml`,
`/tmp/btr/findings-report.md`, `/tmp/btr/repro*.py`. Findings table is authoritative; no re-review performed.

---

## 0. v2 scope decisions (supersede conflicting text below)

Two decisions from the plan review (2026-08-03) narrow this plan. Where §§1–9 conflict with
these, **these win**; the affected sections are annotated inline.

- **D1 — One-directional migration, no bidirectional sync.** The real use case is a repo's
  `.notes/` becoming a symlink to `~/Documents/Notes/<repo_name>/`. At steady state the symlink
  *is* the single source of truth (editing "from either side" hits the same inode — no sync
  needed). Migration runs only once, to seed the target, and only ever copies **link → target**.
  The target→link copy direction is removed entirely. This eliminates the reachability of the
  whole bidirectional-merge risk class (F9/F10/F11/F21/F22 largely evaporate — see §4 notes).
- **D2 — Both-sides-populated is a refusal, not an auto-merge.** When the link path *and* the
  target both hold real content, `apply` refuses with a typed `MigrateCollisionError` (per-link,
  isolated). `--force` moves the target's colliding content aside as conflict files, then seeds
  from the link side. No two-way content interleaving is ever performed.
- **D3 — No locking.** Concurrent `apply` on one project is out of scope. `locking.py`, F14, I7,
  and the exit-4 lock branch are **removed** from this plan. Exit codes remain 0/2/3/4/5 (4 = I/O
  only). A one-line README note states concurrent applies are unsupported.

Fixes to carry into implementation regardless of section text:
- **Verify copies by size (or full hash), NOT strict `st_mtime ==`** — float mtime equality
  false-positives on FAT/exFAT/network filesystems and would fail a correct copy. (Amends I5/F15.)
- **Reclaim staging residue** — remove any stale `<name>.bt-staging-*` for the link path at the
  start of each link's apply; the atomic swap otherwise leaks trees on crash. (Amends I6.)
- **I1 geometry `commonpath` is case-sensitive** — casefold before comparing, or document that the
  geometry invariant assumes a case-sensitive filesystem (hole on macOS/Windows defaults).

---

## 1. Design summary

### 1.1 Target architecture (one paragraph)

Boomtube becomes a **validate → plan → verify → swap** pipeline. Configuration load stays
syntax-only (Pydantic); a new `planning` module renders every template and normalizes every
path *before any filesystem mutation*, rejecting geometrically unsafe configs (link escaping the
project root, link == root, empty/`.` target, link/target nesting) at exit 2 with actionable
messages. The apply flow then mutates one link at a time under a whole-project file lock, each
link going through: runtime re-check of geometry (defense against symlinks created by earlier
links in the same run), kind/type consistency sniffing, a **two-pass verified merge** (scan for
type collisions before copying; skip vanished files; verify every copy by size+mtime before
moving on; conflict artifacts are deterministic and excluded from future merges), and finally an
**atomic swap** (rename the old real path aside, atomically install the symlink, then delete the
renamed tree). `migrate: false` never deletes non-empty real content without an explicit
`--force`. Per-link failures are isolated, summarized, and exit non-zero (5). The CLI is
restructured so `boomtube apply` works on the current typer line, gains a real `boomtube config`
command, and acquires the project lock. The result is a set of invariants that make each
CRITICAL/HIGH failure mode *structurally unreachable* rather than patched-around.

### 1.2 Module responsibilities after refactor

| Module | Responsibility after refactor | Notable new functions / invariants |
|---|---|---|
| `models.py` | Schema + **static, context-free** validation only | `target` non-empty; `link` lexically non-escaping (reject `..`/`.`/`~`/absolute/empty); reject `vars` keys `project_root`/`project_name`; `version` must be int, not bool |
| `config.py` | YAML load + error wrapping | unchanged; wraps `PlanError` from `build_plan` callers |
| `resolve.py` | **All template logic** (vars + targets) | `render_template()` catches `(KeyError, ValueError, IndexError)` → `VarResolutionError`; `build_context` merges builtins last (immutable builtins) |
| `planning.py` *(new)* | Preflight: render targets, normalize paths, enforce geometry | `build_plan(project_root, cfg, ctx) -> list[PlannedLink]`; `PlanError`; invariants I1–I4 |
| `fsops.py` | Atomic FS primitives + type sniffing | `sniff_type()` (lstat → missing/file/dir/symlink/special); `atomic_symlink()` (temp + `os.replace`); `rename_aside()` |
| `migrate.py` | **[D1/D2]** Verified, non-destructive **one-directional (link→target) seed**; refuse when both sides populated | seed link→target only; per-copy **size** verification; `MigrateCollisionError` on both-populated (`--force` → target conflict-files); TOCTOU skip; no write-through/no nesting guards. *(Two-pass bidirectional merge removed.)* |
| `hashing.py` | Content comparison | TOCTOU-tolerant `files_identical` (whole-body `FileNotFoundError` handling) |
| `apply.py` | Orchestration: per-link runtime checks + verified swap | kind consistency (typed errors); `migrate: false` refusal; special-file refusal; apply-time geometry re-check; verify-before-swap; atomic swap; per-link isolation; `RunResult` |
| `cli.py` | Entry points, lock, exit codes | callback restructure (F7); `boomtube config` command; exit codes 0/2/3/4/5 |
| ~~`locking.py` *(new)*~~ | **[D3] Removed** — concurrent apply out of scope | — |
| `util.py` | Naming / unique paths | deterministic conflict-name helper; `unique_path` retained |

### 1.3 Invariants the new design guarantees

- **I1 — Geometry (config-load-time):** every link path is strictly inside the project root and
  never equals it; every target is non-empty, never equals the project root, and is **disjoint**
  from its link (not equal, neither contains the other). Enforced in `build_plan` (exit 2, before
  mutation).
- **I2 — Geometry (apply-time):** geometry from I1 is re-verified per link immediately before
  mutation, using the *current* filesystem state (catches parents that became symlinks through
  earlier links in the same run). Violation → per-link error, link untouched.
- **I3 — Templates:** all vars and all targets are fully rendered during preflight; template
  errors (`KeyError`/`ValueError`/`IndexError`) surface as typed `VarResolutionError` (exit 2)
  before any mutation.
- **I4 — Builtins:** `project_root`/`project_name` can never be overridden by user vars.
- **I5 — No unverified deletion:** no file or directory is removed until a **size-verified**
  (per-copy) copy exists at its destination, and every file in the pre-seed snapshot of the link
  tree has a verified copy in the target tree. *(Amended: size, not size+mtime.)*
- **I6 — Atomic swap:** symlink creation/replacement uses temp-symlink + `os.replace`; converting
  a real file/dir to a symlink uses rename-aside so the old tree survives any crash point and is
  deleted only after the new link exists. Stale `<name>.bt-staging-*` is reclaimed at link start.
- ~~**I7 — Serialized runs**~~ **[D3] Removed** (no locking).
- **I8 — `migrate: false` is non-destructive:** refusal (per-link) whenever the link path holds
  non-empty real content, unless the caller passes `--force`.
- **I9 — [D1/D2] One-directional seed, no both-sides merge:** migration copies **link → target
  only**; when both the link path and target hold real content, `apply` refuses
  (`MigrateCollisionError`) unless `--force` (which conflict-files the target side first). `_copy`
  refuses to nest or write through symlinks. *(Supersedes the two-pass bidirectional pre-scan.)*
- **I10 — Inert conflicts:** `.conflict-from-project-*` artifacts (from `--force` collision
  handling) are excluded from copying and named deterministically per content, so re-runs are
  idempotent.

---

## 2. Control-flow notes (as-read, pre-refactor)

- **models.py** — Pydantic models. `LinkSpec.link` validator only rejects absolute, `~`-prefixed,
  empty. `target` has *no* validator. `migrate` defaults to `True` (contradicting README, F17).
  `BoomtubeConfig` requires `version == 1` and non-empty links.
- **config.py** — reads YAML, `yaml.safe_load`, validates via pydantic, wraps `ValidationError`
  into `ConfigError`. Pure load; no path context.
- **resolve.py** — `render()` and `resolve_vars()` use `str.format_map` with a lazy `_Ctx`
  mapping; only `KeyError` is caught (F5: `ValueError`/`IndexError` escape; F6: targets are never
  rendered through this code at all). `build_context` merges user vars *over* builtins (F16).
- **fsops.py** — `normalize_path` (`~` expansion, resolve relative to base, `resolve(strict=False)`);
  `symlink_to` (mkdir parents then `symlink_to`); `remove_path` = unlink for symlink/file, else
  `shutil.rmtree` (the data-loss primitive, reached unconditionally at apply.py:89).
- **hashing.py** — `sha256` (unprotected open) and `files_identical` (stat guarded for
  `FileNotFoundError`, returns False; but `sha256` call inside can still race, F11).
- **migrate.py** — `migrate_file`: guards on `exists()` (broken symlink → "missing", F21);
  copy direction by mtime with `_MTIME_EPS=1e-3`, tie → conflict copy to B side.
  `migrate_dir`: `_list_files` walks with `os.walk(followlinks=False)`, skips symlinks and
  non-files; merge loops over union of rels, `copy2` for copies; **no type-collision detection**
  (F9: `copy2` on a dir/file mismatch either crashes or silently nests), **no conflict-file
  exclusion** (F10), **no per-copy verification** (F15).
- **apply.py** — `detect_kind` (explicit kind wins, then link type, target type, dot-folder
  heuristic). `apply_link`: normalize paths, `ensure_parent_dir`, mkdir target, then branch:
  missing → symlink; symlink → `_same_target` or replace; real → migrate (if `spec.migrate`)
  then **unconditional `remove_path(link_path)` + `symlink_to`** (F2). No geometry checks (F1,
  F3, F4, F13). `target.format_map(ctx)` unguarded (F6). `apply_all` has no per-link try/except
  (F12).
- **cli.py** — single `@app.command()` Typer app; under typer 0.27.1 this auto-invokes, so
  `boomtube apply` fails (F7). Exit codes 2/3/4 (F19). No `config` command (F18).
- **util.py** — `conflict_timestamp()` + `unique_path()` (`-1`, `-2`… suffixes → F10 spread).
- **apply_link sequences** — (i) *missing link:* mkdir parents, mkdir target, `symlink_to`; done.
  (ii) *correct symlink:* `is_symlink` → `_same_target` true → log "already correct", no mutation.
  (iii) *stale symlink:* `remove_path` (unlink) then `symlink_to`. (iv) *real file/dir, migrate:
  true:* `migrate_dir/migrate_file` in place (both directions), then `remove_path` (rmtree) then
  `symlink_to` — the F1/F4/F13 path. (v) *real file/dir, migrate: false:* skip merge, straight to
  `remove_path` + `symlink_to` — the F2 silent-deletion path.

---

## 3. Design traces (CRITICAL / HIGH)

### F1 — target inside link tree (CRITICAL)
- **Current failure path:** `link: .notes`, `target: .notes/backup`, real data at link. Target
  mkdir'd *inside* the link tree; `migrate_dir` merges overlapping trees (copies land inside the
  tree about to be deleted); `remove_path(.notes)` rmtrees everything including the "backup";
  dangling symlink remains.
- **Proposed design:** I1 rejects target-inside-link (and link-inside-target, and equality) at
  preflight via `os.path.commonpath` on resolved paths → exit 2, zero mutation. I2 re-checks per
  link at apply time. I5 adds defense in depth: the swap only proceeds after every file from the
  link's pre-merge snapshot has a verified copy in the target.
- **Why impossible:** any config that nests the trees never reaches the merge or the `rmtree`;
  the only way to delete the link tree is after (a) geometry is disjoint, and (b) a verified copy
  of every snapshot file exists in the target. The exact `rmtree` that destroyed the data in the
  repro can no longer run with overlapping trees.

### F2 — `migrate: false` silently destroys (CRITICAL)
- **Current failure path:** real file/dir at link path, `spec.migrate == False` → no merge, but
  `remove_path(link_path)` still runs (apply.py:89) → `rmtree`/unlink, no warning, target empty.
- **Proposed design (I8):** before the swap, if `migrate: false` and the link path holds
  non-empty real content (not a symlink, not an empty directory), raise `MigrateDisabledError`
  (per-link, isolated). Caller must pass `--force` to replace without merging.
- **Why impossible:** the only paths that reach `remove_path` on real content are (a) `migrate:
  true` after verified merge, or (b) `migrate: false` with explicit `--force` (an intentional,
  disclosed destructive action). The silent `rmtree` in the repro is refused before it runs.

### F3 — `link: ../outside` escapes project root (CRITICAL)
- **Current failure path:** `link: ../outside` (or `a/../../b`) passes the "relative" check;
  `link_path = project_root / "../outside"` escapes; mkdir/rmtree/symlink operate on sibling user
  data.
- **Proposed design (I1):** preflight computes `(project_root / link).resolve(strict=False)` and
  requires `commonpath([root, link]) == root` and `link != root`; `build_plan` rejects escapes
  with an actionable message. I2 re-checks at apply time after parent creation (guards the
  order-created-symlink-parent case).
- **Why impossible:** the path that reaches `remove_path`/`symlink_to` is the *validated* planned
  path, which provably resolves inside the project root at preflight and is re-verified at apply
  time against the live filesystem.

### F4 — `link: "."` deletes the project root (CRITICAL)
- **Current failure path:** `link: "."` → `link_path == project_root`; `migrate_dir(proj, proj)`
  sees everything identical; `remove_path(proj)` rmtrees the entire project; reported success.
- **Proposed design (I1):** `(project_root / ".").resolve() == project_root` → reject at
  preflight (link must not equal root). Empty/`.` targets rejected (F13) so target can't equal
  root either. Defense in depth: `apply.py` refuses to call `remove_path` on any path equal to
  the project root or one of its ancestors.
- **Why impossible:** both the link and target are validated to be non-root before anything runs,
  and the deletion primitive is additionally guarded against root/ancestor paths.

### F5 — `{}`/stray braces crash with `ValueError` (HIGH)
- **Current failure path:** `"{}".format_map(ctx)` raises `ValueError`; every handler catches only
  `KeyError`; raw traceback, exit 1.
- **Proposed design (I3):** single `render_template()` wrapping `format_map` in
  `except (KeyError, ValueError, IndexError)` → `VarResolutionError`; used by `resolve_vars` and
  by target rendering in `build_plan`.
- **Why impossible:** no template is ever rendered outside `render_template`; all three exception
  classes are normalized to the typed error, which the CLI maps to exit 2.

### F6 — missing var in target, discovered mid-run (HIGH)
- **Current failure path:** `target: "{missing}/x"` renders via unguarded `format_map` at apply
  time → raw `KeyError` after earlier links already mutated the FS.
- **Proposed design (I3):** `build_plan` renders **all** targets during preflight (before any
  mutation) with the typed `render_template`; missing vars → `VarResolutionError`, exit 2.
- **Why impossible:** targets are rendered to completion during preflight; `apply` never
  encounters an unrendered template, so no run can fail on a missing var after starting to mutate.

### F7 — `boomtube apply` broken under typer 0.27.1 (HIGH)
- **Current failure path:** a single-`@app.command()` Typer app auto-invokes its sole command as
  root under modern typer, so `apply` becomes "unexpected extra argument"; only bare `boomtube`
  (which auto-runs apply on cwd) works. Verified locally (exit 2).
- **Proposed design:** add a root `@app.callback()` + keep `apply` as an explicit named
  subcommand (structure verified working on typer 0.27.1); set `no_args_is_help=True` so bare
  invocation prints help instead of auto-applying. CI matrix tests the full supported typer range
  (`>=0.12`).
- **Why impossible:** with a callback present, typer never auto-invokes a subcommand; `boomtube
  apply` always dispatches to the subcommand, and bare invocation is inert help output (no more
  surprise apply-on-cwd).

### F8 — kind misdetection crashes (HIGH)
- **Current failure path:** explicit `kind: file` + real dir at link → `migrate_file` →
  `IsADirectoryError` mid-run; `kind: dir` + real file → `FileExistsError`; run aborts with
  partial state.
- **Proposed design:** `sniff_type()` (lstat) at the link path before merge; explicit kind vs
  reality mismatch → typed `KindMismatchError` (per-link, isolated, clear message). Auto-detection
  order preserved.
- **Why impossible:** the merge dispatch never receives a `kind` that contradicts the actual
  type at the link path; mismatches surface as named errors for that link only, and I12 (per-link
  isolation) keeps the run alive.

### F9 — dir-merge type collision (HIGH)
- **Current failure path:** A has file `x`, B has dir `x/` → `copy2`/mkdir conflict →
  `FileExistsError` crash mid-merge (partial state); and `copy2(file, existing_dir)` *silently
  nests* the file as `x/x` instead of failing.
- **Proposed design (I9):** `migrate_dir` becomes two-pass: (1) walk both trees recording
  rel→type; raise `TypeCollisionError` (listing the rels) if any rel is a dir on one side and a
  file on the other — before any copy; (2) merge. `_copy` defensively refuses when dst is a
  symlink (write-through) or an existing dir (nesting).
- **Why impossible:** no merge pass starts unless the full type map is collision-free, so no
  copy can land on a conflicting node; the silent-nest and crash paths both become pre-scan
  errors, and per-link isolation prevents whole-run aborts.

---

## 4. Per-finding resolution table

| F# | Sev | Design decision | Module(s) | Behavior change? | Residual risk |
|----|-----|-----------------|-----------|------------------|---------------|
| F1 | CRITICAL | Reject link/target nesting at preflight (I1) + apply-time re-check (I2) + verify-before-swap (I5) | planning.py, apply.py | **Yes** — nested configs now error (exit 2) instead of destroying data. Rationale: configs of this shape are data-loss hazards by construction. | Symlink-based nesting created mid-run by earlier links: covered by I2 re-check + I5 verify. |
| F2 | CRITICAL | `migrate: false` + non-empty real content → `MigrateDisabledError` unless `--force` (I8) | apply.py, cli.py | **Yes** — silent replace of real content is refused; users relying on it need `--force`. Rationale: README promises no silent deletion. | Explicit `--force` is an intentional opt-in; disclosed in error text and README. |
| F3 | CRITICAL | Reject link escaping root (lexical in models + resolved in `build_plan`) (I1/I2) | models.py, planning.py, apply.py | **Yes** — `../` configs now fail validation (exit 2). Rationale: they operate outside the project. | Order-created symlink parents: apply-time re-check catches. |
| F4 | CRITICAL | Reject link == root and target == root; guard `remove_path` against root/ancestors | planning.py, apply.py | **Yes** — `link: "."` configs now fail (exit 2). Rationale: `rmtree(project_root)` is unrecoverable. | None. |
| F5 | HIGH | `render_template` catches `(KeyError, ValueError, IndexError)` → `VarResolutionError` | resolve.py | **Yes** — stray-brace configs go from traceback (exit 1) to clean error (exit 2). | None. |
| F6 | HIGH | Pre-render all targets in `build_plan` before mutation | planning.py, resolve.py | **Yes** — missing var discovered at load (exit 2), not mid-run. | None. |
| F7 | HIGH | Root callback + named subcommand; `no_args_is_help` | cli.py | **Yes** — bare `boomtube` stops auto-applying (prints help); `boomtube apply` works. | Unverified on typer 0.12–0.13 → CI version matrix in P3. |
| F8 | HIGH | `sniff_type` + typed `KindMismatchError`; per-link isolation | apply.py, fsops.py | **Yes** — raw `IsADirectoryError`/`FileExistsError` become named per-link errors. | None. |
| F9 | HIGH | **[D1]** Single link-side pre-scan vs target for dir/file collisions; no-nest/no-write-through `_copy` | migrate.py | **Yes** — collisions error before mutating (previously crash w/ partial state or silent nest). | None beyond configs the user must fix. |
| F10 | MEDIUM | Exclude `.conflict-from-project-*` from `_list_files`; deterministic hash-based names; skip if identical conflict exists | migrate.py, util.py | **Yes** — conflict file format/name changes (`…-{sha8}`), re-runs idempotent. | Orphan hash-named files linger after content changes (inert, excluded, user-deletable). |
| F11 | MEDIUM | Per-file `FileNotFoundError` → skip vanished file; TOCTOU-tolerant hashing; verify pass re-lists link tree at swap | migrate.py, hashing.py, apply.py | **No** (crash → skip/loud per-link error). | External non-boomtube processes still race the swap; inherent to "replace with symlink". |
| F12 | MEDIUM | Per-link try/except + continue + `RunResult` summary + exit 5 | apply.py, cli.py | **Yes** — run no longer aborts at first failure; exit 5 added. | None. |
| F13 | MEDIUM | Reject empty/`.` target and rendered-empty target; target != project root | models.py, planning.py | **Yes** — empty-target configs now fail (exit 2). Rationale: self-referential symlink + recursion trap. | None. |
| F14 | MEDIUM | **[D3] Not addressed** — concurrent apply out of scope; locking removed. README notes concurrent applies are unsupported. | README | **No** (docs only) | Concurrent applies on one project can still race; verify-before-swap + atomic swap keep the worst case a clean per-link failure, not corruption. |
| F15 | LOW | Per-copy size+mtime verification; verify-before-swap; atomic swap | migrate.py, apply.py, fsops.py | **Yes** — copies are verified and swap is crash-safe; slightly more I/O. | Same-size bit corruption undetected by size+mtime check (full-hash optional, open Q8). |
| F16 | LOW | Reject user vars named `project_root`/`project_name`; builtins merged last | models.py, resolve.py | **Yes** — shadowing vars now fail validation (exit 2). Rationale: shadowing silently rewrites every `{project_root}` path. | None. |
| F17 | LOW | Keep code default `migrate: true`; fix README (default was documented as false) | README, models.py (unchanged) | **Yes** (docs) — README now matches code. | None. |
| F18 | LOW | Implement `boomtube config` (resolved-config preview via `build_plan`) | cli.py, planning.py | **Yes** — new command. | None. |
| F19 | LOW | Document exit codes 0/2/3/4/5 (2 config/preflight, 3 permission, 4 I/O, 5 apply-time failures) | cli.py, README | **Yes** — exit 5 added; README corrected. | External scripts relying on exit 1 for failures. |
| F20 | LOW | `sniff_type == "special"` at link path → `UnsupportedLinkTypeError` (per-link) | apply.py | **Yes** — FIFO at link path now cleanly refused (was `SpecialFileError` → exit 4). | Special files *inside* walked dirs remain skipped silently (documented). |
| F21 | LOW | `migrate_file` symlink guard order: `is_symlink()` before `exists()` (lexists semantics) | migrate.py | **No** for apply flow (already safe); **Yes** for direct API (no more write-through). | None. |
| F22 | INFO | No code change; document sub-ms mtime tie noise | README | No | Documented. |
| F23 | INFO | README wording: "dependency-ordered resolution with cycle detection" | README | No (docs) | None. |
| F24 | INFO | Reject `version: yes` (bool) with a clear message | models.py | **Yes** — `version: yes` fails validation (was accepted as 1). | None. |

Deliberate behavior-change summary (all flagged above): rejections for F1/F3/F4/F13/F16/F24
configs; F2 refusal + `--force`; F5/F6 error normalization; F7 CLI restructure; F8/F9/F20 typed
errors; F10 conflict naming; F12/F19 exit 5 + continue-on-error; F14 locking; F18 new command;
F17/F19/F23 README corrections. Each ships with the message/README text needed to migrate
existing configs (see §6).

---

## 5. Phased implementation plan

Ordering rationale: P0 removes the config-controlled *destruction* class and makes the CLI usable
(foundation, strictly safer). P1 then hardens the remaining destructive primitives (deletion is
verified, atomic, serialized; `migrate: false` safe) — this is where the dangerous operations
live, so it must include per-link isolation (a refusal that aborts the whole run would be a
behavioral regression). P2 fixes merge semantics (crash/partial states). P3 is CLI/UX polish.
P4 aligns docs and tests. No phase is more dangerous than its predecessor: each only refuses
earlier, verifies more, or converts crashes into contained errors.

### Phase 0 — Safety validation & usable CLI (F1, F3, F4, F5, F6, F7, F13, F16, F24)

Goal: every config-controlled data-loss hazard and every template crash is rejected **before any
filesystem mutation**; `boomtube apply` works again.

Tasks (function-level):
1. `models.py`
   - Add `target_must_be_non_empty` field validator (reject `""`, whitespace-only).
   - Tighten `link_must_be_relative`: reject `.` and `..` exactly, reject any path containing a
     `..` component (`../x`, `a/../../b`), keep absolute/`~`/empty rejections.
   - `BoomtubeConfig.validate_config`: reject `version` of type `bool`; reject `vars` keys
     `project_root`/`project_name` with a clear message.
2. `resolve.py`
   - Add `render_template(template, ctx)` wrapping `format_map` in
     `except (KeyError, ValueError, IndexError)` → `VarResolutionError`.
   - Replace both raw `format_map` call sites with `render_template`.
   - `build_context`: return `{**resolved_user, **builtins}` (builtins win).
3. `planning.py` (new)
   - `PlannedLink` frozen dataclass: `spec`, `link_path`, `target_path`, `migrate`.
   - `build_plan(project_root, cfg, ctx)`:
     - render every `spec.target` with `render_template`;
     - `link_path = (project_root / spec.link).resolve(strict=False)`;
       `target_path = normalize_path(Path(rendered), base=project_root)`;
     - checks → `PlanError` (exit 2): link != root; `commonpath([root, link]) == root`;
       target non-empty after strip; target != root; `commonpath([link, target])` is neither
       link nor target (disjoint; catch `ValueError` from `commonpath` → treat as disjoint, e.g.
       different drives);
     - return list of `PlannedLink`.
4. `apply.py`
   - `apply_all(project_root, specs, ctx, *, force=False)` → builds plan then delegates;
     keeps library callers (and existing tests) working.
   - New `apply_plan(project_root, planned, *, force=False)`: P0 body = loop, but with per-link
     try/except stub introduced here so preflight rejections cannot abort the run (see P1).
5. `cli.py`
   - Add root `@app.callback()`; `@app.command(name="apply")`; `no_args_is_help=True` (F7).
   - Call `build_plan` before applying; `PlanError`/`ConfigError`/`VarResolutionError` → exit 2.
6. `locking.py` (new, stub): `project_lock(project_root)` context manager; in P0 acquire only
   (full semantics in P1).

Behavior changes: F1/F3/F4/F13/F16/F24 configs rejected at load (exit 2, zero mutation);
template errors typed (exit 2); `boomtube apply` works; bare `boomtube` shows help.

New tests: `test_planning.py` (containment/overlap/root/empty-target matrix incl. `a/../../b`,
`.` target, rendered-empty target, different-drive disjoint); `test_resolve.py` (stray braces,
positional fields → `VarResolutionError`; builtins immutable); `test_config.py` (version bool,
shadowing vars); `test_cli.py` (apply subcommand works under current typer; bare invocation shows
help; exit 2 paths). Ported regressions: repro1, repro3/3b, repro4, repro6/6b, repro13-as-preflight
(missing var), repro6-empty-target.

Exit criteria: all repro configs above exit 2 with actionable messages and provably zero FS
mutation (tests assert project tree unchanged); `boomtube apply` green under installed typer;
existing 27 tests still pass.

### Phase 1 — Apply-flow data-loss hardening (F2, F8, F11, F15, F20, F21, F12-core) — **[D1/D2/D3 revised]**

Goal: deletion only after size-verified duplication + atomic swap; `migrate: false` never
destructive; migration is **one-directional (link→target)**; both-populated is refused; mismatches
typed and isolated. *(Locking removed — D3.)*

Tasks:
1. `fsops.py`
   - `sniff_type(path)` → `"missing" | "file" | "dir" | "symlink" | "special"` (lstat).
   - `atomic_symlink(link, target)`: build `link.bt-tmp-<pid>`, `symlink_to` it, `os.replace`
     over `link` (atomic for missing/stale-symlink cases).
   - `rename_aside(path) -> Path`: `os.replace(path, path.with_name(name + ".bt-staging-<pid>"))`;
     returns staging path (same-fs atomic move). Reclaim any stale `<name>.bt-staging-*` first.
2. `migrate.py` — **[D1]** becomes a one-directional seed, not a bidirectional merge.
   - `seed_dir(link_dir, target_dir)` / `seed_file(link, target)`: copy link→target only. **No
     target→link branch.**
   - **[D2]** If both sides hold real content at the same rel (or both roots are non-empty),
     raise `MigrateCollisionError` (list the rels) *before any copy*; `--force` → move the
     target-side colliding files aside as deterministic conflict files, then seed.
   - `_copy`: after `copy2`, verify `dst.stat().st_size == src.stat().st_size` (**size only** —
     mtime equality is unreliable across filesystems); else raise (F15).
   - Symlink guards: skip symlinks on both sides (F21); `_copy` refuses to nest or write through
     a symlink at the destination.
   - Wrap per-file stat/hash/copy in `try/except FileNotFoundError` → skip (log debug) (F11).
   - `snapshot_files(root)` for apply-time verify.
3. `hashing.py`: wrap whole `files_identical` body in `FileNotFoundError → False`.
4. `apply.py`
   - Per-link sequence: re-check geometry (I2) → `sniff_type` link → kind consistency
     (`KindMismatchError`) → special file (`UnsupportedLinkTypeError`) → `migrate: false`
     non-empty check (`MigrateDisabledError`, unless `force`) → both-populated check
     (`MigrateCollisionError`, unless `force`) → seed link→target (verified) → verify
     snapshot-vs-target → atomic swap.
   - Verify-before-swap (I5): take pre-seed snapshot of the link tree; after seeding, for each
     snapshot file confirm a **size-verified** copy at the same rel in target; failure → per-link
     error, link tree left intact (no rename, no rmtree).
   - Swap (I6): reclaim stale staging; `staging = rename_aside(link_path)`;
     `atomic_symlink(link_path, target_path)`; `remove_path(staging)`. Guard: never call
     `remove_path` on project root/ancestors.
   - `apply_plan` per-link try/except collecting `RunResult(applied: list[Path],
     failed: list[tuple[Path, Exception]])`; continue on failure (F12-core).
5. ~~`locking.py`~~ — **[D3] removed.**
6. `cli.py`: `--force` flag (threads to `apply_plan`); map `RunResult.failed` non-empty → exit 5
   with summary. *(No lock-error mapping.)*

Behavior changes: `migrate: false` + non-empty → refusal (exit 5) unless `--force`; both-populated
→ refusal unless `--force`; migration is one-directional; typed kind/special errors; vanished files
skipped; deletion now size-verified + atomic; per-link continuation with summary.

New tests: `test_apply.py` (migrate:false refusal / empty-dir allow / `--force` override; kind
mismatch typed errors; special file refusal; verify-failure aborts link with data intact —
monkeypatch `copy2` to truncate; root-rmtree guard); `test_fsops.py` (atomic swap crash windows:
fail after rename → staging residue + data intact; fail after symlink → clean state; `os.replace`
atomicity); `test_migrate.py` (vanished file skipped; broken-symlink guard; per-copy verify);
`test_locking.py` (second lock acquisition fails; lock released after run);
`test_cli.py` (exit codes 4/5; summary text; `--force` path). Ported regressions: repro2,
repro5, repro10b, repro11 (subprocess), repro13, repro15.

Exit criteria: repro2 leaves data intact and reports exit 5; repro11 second process refuses
cleanly with no crash; truncated-copy simulation leaves the link tree intact; crash-window
simulations never lose data; all earlier repros still rejected/safe.

### Phase 2 — Seed correctness (F9, F10) — **[D1 revised: much reduced]**

Goal: no partial/crashy seed states; conflict artifacts inert and idempotent. **[D1]** With
one-directional seeding, the bidirectional two-pass merge and its re-merge idempotency problem
(F10) are no longer reachable through `apply`; what remains is a small set of guards folded here.

Tasks:
1. `migrate.py`
   - Pre-scan the link tree once (lstat, rel→type) before seeding; a dir-vs-file collision against
     an existing target node → `MigrateCollisionError` listing rels — **before any copy** (F9).
     *(Was a two-pass bidirectional scan; now a single link-side scan vs target.)*
   - `_copy` guards: dst exists and `is_symlink()` → refuse (no write-through); dst exists and
     `is_dir()` while src is a file → refuse (no silent nesting).
   - F10: exclude `*.conflict-from-project-*` from seeding; conflict naming (used only by the
     `--force` collision path) becomes `{name}.conflict-from-project-{sha256(content)[:8]}`; skip
     creation when a file with that name already has identical content.
2. `util.py`: update conflict-name helper (content hash); `unique_path` retained.

Behavior changes: dir/file collisions → clean per-link error before any byte is copied (was crash
+ partial state or silent nesting); conflict files (from `--force`) excluded from seeding;
deterministic names (re-runs idempotent). *(Bidirectional re-merge duplication no longer possible.)*

New tests: `test_migrate.py` (pre-scan raises before mutation — assert zero copies; no-nest; no
write-through); `test_conflicts.py` (run twice → stable, no `-1` duplicates, excluded from
merge; deterministic name = f(rel, content)). Ported regressions: repro7, repro9b.

Exit criteria: repro7 → typed error, zero partial state; repro9b → identical state after run 1
and run 2.

### Phase 3 — CLI & UX (F18, F19, F7-matrix, F12-polish)

Goal: documented commands work; exit-code contract stable; useful summaries.

Tasks:
1. `cli.py`
   - Add `boomtube config` command: `load_config` → `build_context` → `build_plan` → print
     resolved config as YAML (rendered targets + resolved vars + kinds); errors → exit 2 (F18).
   - Apply summary: "Applied 4/5 links; failed: .env — kind mismatch (link: .env, target: …)".
   - Keep exit mapping 0/2/3/4/5 stable (F19).
2. `pyproject.toml`: add CI note / dev tooling for a typer version matrix (0.12.x … current) —
   no dependency change required by the fix; document that the callback structure is
   version-independent. (Only if the matrix finds a regression would we pin; plan avoids pinning.)
3. Polish `apply_plan` return/error surfaces for the CLI.

Behavior changes: new `boomtube config` command; exit 5 documented; failure summaries.

New tests: `test_cli.py` (config command output correctness incl. rendered targets; exit codes
0/2/3/4/5 end-to-end; version-matrix test script run in CI: invoke `boomtube apply --help` under
typer 0.12 and current).

Exit criteria: every README-documented command works end-to-end; exit codes asserted by tests.

### Phase 4 — Docs & test cleanup (F17, F19, F22, F23 + behavior docs)

Goal: README matches code; tests assert the new invariants, not the old bugs.

Tasks:
1. README edits per §6 (F17, F19, F22, F23, new safety/validation/conflict/locking/exit-code
   sections).
2. Rewrite `tests/test_detect_kind.py` for the new sniff/consistency API.
3. Sweep remaining tests for stale expectations; add the invariant unit tests from §7 that are
   not yet present.

Behavior changes: none in code (docs/tests only).

Exit criteria: README claim-vs-code diff zero (review checklist); full suite green; coverage
meaningful (≥90% on apply/planning/migrate/cli).

---

## 6. Documentation update list (README)

| # | Current claim / text | Replacement wording |
|---|---|---|
| 1 | "`migrate` … (default: `false`)" (lines ~116, ~158) | "`migrate` … (default: `true`). When `migrate: false` and the link path already contains real files or directories, `boomtube apply` refuses and exits 5 — pass `--force` to replace without migrating." (F17, F2) |
| 2 | "Exit Codes: 0 success, 1 failure" | "0 success · 2 config/validation/var-resolution error (nothing was changed) · 3 permission error · 4 I/O or lock error · 5 one or more links failed to apply (others may have succeeded)" (F19) |
| 3 | "`boomtube config`" section | Keep, now accurate: "validates the config and prints the fully resolved plan (all variables and targets interpolated) without changing anything." (F18) |
| 4 | Conflict-file format `{original}.conflict-from-project-{timestamp}` | `{original}.conflict-from-project-{sha256-of-content (8 chars)}`; conflict files are excluded from future merges; re-running an apply is idempotent w.r.t. conflicts. (F10) |
| 5 | "Variable Resolution: Topological sort …" | "Dependency-ordered resolution with cycle detection (DFS memoization); `project_root`/`project_name` are built-in and cannot be overridden by user vars." (F23, F16) |
| 6 | "Safety First: Never delete data without migration or explicit user action" | Expand into a "Safety guarantees" section: validation rejections (link outside root, link == root, empty/`.` target, link/target nesting), verified copies before deletion, atomic replacement, single apply at a time per project, `migrate: false` refusal without `--force`. (F1-F4, F13-F15) |
| 7 | "Auto-detection rules …" | Add: "a `kind` that contradicts the real file/dir type at the link path is a per-link error (exit 5), not a crash." (F8) |
| 8 | "Migration Behavior" sections | Add: dir/file type collisions are detected before anything is copied and reported as a per-link error; files that disappear mid-migration are skipped; every copy is verified (size + mtime) before its source can be removed. (F9, F11, F15) |
| 9 | Conflict noise | Document that sub-millisecond mtime differences on coarse-granularity filesystems can produce conflict files (by design). (F22) |
| 10 | Migration chapter example/format claims | Reflect atomic swap + lock: "Each link is applied atomically; the old path is moved aside, the symlink installed, then the old tree removed. Concurrent applies on the same project are refused." (I6, I7) |
| 11 | Version note | `version` must be an integer; `version: yes` is rejected. (F24) |

---

## 7. Test plan

### 7.1 New unit tests (per invariant)

- **I1/I2 geometry:** `test_planning.py` — link `..`, `a/../../b`, `.`, empty; target `""`,
  `"."`, rendered-empty `"{empty}"`; target-inside-link, link-inside-target, equal, disjoint
  (incl. `commonpath` `ValueError` → disjoint); apply-time re-check when a parent became a
  symlink mid-run (build plan, create symlink, apply → per-link error, no escape).
- **I3 templates:** `test_resolve.py` — `{}`, `{`, `{x`, `{0}` (IndexError path), missing key →
  all `VarResolutionError`; targets pre-rendered in `build_plan`.
- **I4 builtins:** shadowing var rejected at config; `build_context` merge order.
- **I5 verified deletion:** monkeypatch `copy2` to truncate → migration aborts, link tree intact;
  verify pass compares snapshot vs target.
- **I6 atomic swap:** crash simulation via monkeypatched `os.replace`/`remove_path`: fail between
  rename and symlink (staging residue, data intact, link missing, rerunable); fail after symlink
  (clean). Stale-symlink replace via `atomic_symlink` is a single `os.replace`.
- **I7 locking:** second `project_lock` acquisition fails (exit 4); released after run.
- **I8 migrate:false:** refusal; empty-dir allowance; `--force` override.
- **I9 no partial merges:** collision pre-scan raises before any copy (assert zero files changed);
  `_copy` no-nest / no-write-through.
- **I10 inert conflicts:** exclusion from `_list_files`; deterministic name; re-run stability.

### 7.2 Regression tests mapped to F1–F24 (repro scripts ported)

| F# | Regression test (source) |
|----|--------------------------|
| F1 | port `repro1_target_inside_link.py` → assert `PlanError`, project untouched |
| F2 | port `repro2_migrate_false_delete.py` → assert refusal, data intact, exit 5 |
| F3 | port `repro3_link_dotdot.py`, `repro3b_link_dotdot_nomigrate.py` → validation rejection |
| F4 | port `repro6b_link_dot.py` → rejection, project root intact |
| F5 | port `repro4_braces_crash.py` (cases 1, 3) → `VarResolutionError`, no traceback |
| F6 | port `repro4_braces_crash.py` (case 2) → preflight error before any mutation |
| F7 | port `/tmp/btr/clitest` configs + `CliRunner.invoke(app, ["apply", …])` → exit 0 |
| F8 | port `repro5_kind_file_on_dir.py`, `repro12_edgecases.py` case 3 → typed per-link errors |
| F9 | port `repro7_type_collision.py` / `repro7c_trace.py` → pre-scan error, zero partial state |
| F10 | port `repro9b_conflict_spread.py` → run1/run2 stable, no `-1` duplicates |
| F11 | port `repro13_toctou.py` (interpose on `files_identical`) → skipped, no crash |
| F12 | port `repro15_abort.py` → `.good` applied, `.bad` reported, exit 5 |
| F13 | port `repro6_empty_target.py` → validation rejection |
| F14 | port `repro11_concurrent.py` / `repro11b` → second process lock-refused, no crash |
| F15 | new: truncated-copy simulation (monkeypatch) → swap aborted, data intact |
| F16 | new: shadowing var rejected; builtins immutable |
| F17 | new: `LinkSpec(link="x", target="y").migrate is True`; README diff review |
| F18 | new: `boomtube config` exists, prints resolved plan |
| F19 | new: CLI exit codes 0/2/3/4/5 asserted end-to-end |
| F20 | port `repro10b_fifo.py` → typed refusal, FIFO left in place |
| F21 | new: `migrate_file` on broken symlink does not write through |
| F22 | new: sub-ms tie → conflict (documents current design; change → update test) |
| F23 | docs review only |
| F24 | new: `version: yes` rejected |

### 7.3 Tests to delete / rewrite

- **Rewrite:** `tests/test_detect_kind.py` — `detect_kind` is replaced by
  `sniff_type` + consistency checks; tests must target the new API.
- **Keep as-is (verified compatible):** all of `test_config.py`, `test_resolve.py`,
  `test_apply_symlink.py`, `test_migrate_files.py`, `test_migrate_dirs.py` — none assert buggy
  behavior; conflict-glob assertions (`f.txt.conflict-from-project-*`) still match the new
  deterministic names. Minor: if `apply_all` gains keyword-only params, existing callers are
  unaffected (defaults preserve behavior).
- **Delete:** none. (No test asserts the destructive paths; the suite's weakness is missing
  coverage, not wrong assertions.)

---

## 8. Open questions (decision-ready)

1. **F2 escape hatch.** Refuse + global `--force` CLI flag (recommended) vs per-link `replace:
   true` YAML field (more declarative, schema change) vs no override (users must use
   `migrate: true`). Trade-off: `--force` is simplest and explicit; per-link field is finer-
   grained but adds schema surface; no override is safest but least flexible.
2. **F10 conflict naming.** Hash-based deterministic `{name}.conflict-from-project-{sha8}`
   (recommended; idempotent, loses human-readable timestamp) vs timestamp + dedupe (readable,
   re-run duplication remains) vs exclude-only (fixes spread but not duplication). Trade-off:
   hash names sacrifice "when was this?" for idempotency; the timestamp remains in file mtime.
3. **Exit code 5.** New code for apply-time per-link failures (recommended) vs reuse 4 vs keep
   documented 1. Trade-off: 5 is unambiguous for scripts; 4 conflates I/O with logic errors; 1
   matches the old README but loses granularity.
4. **F16 shadowing.** Reject user vars named `project_root`/`project_name` (recommended,
   fail-fast) vs silently prefer builtins (backward-compatible, masks config bugs). Trade-off:
   rejection is a deliberate breaking change for configs that (incorrectly) shadow.
5. **F9 collisions.** Error the link before mutating (recommended, fail-fast) vs preserve as a
   conflict file (friendlier, silently changes merge semantics). Trade-off: error forces the
   user to resolve ambiguity; conflict-preservation keeps both versions but complicates the
   verified-deletion invariant (a "copy" that is not at the same rel).
6. **Lock scope.** Whole-run flock on the project-root directory fd (recommended; zero residue,
   serializes all applies in the project) vs a `.boomtube.lock` file (visible residue, unlink
   races) vs per-link locks (parallel-friendly, complex) vs none. Also: non-blocking refusal
   (recommended) vs blocking with timeout. Trade-off: non-blocking is predictable for scripting;
   blocking is friendlier interactively. Note advisory-flock/NFS/Windows caveats.
7. **Verify strength (F15).** Size + mtime (recommended; cheap, catches truncation) vs full
   sha256 of every copied file (stronger, extra read I/O). Trade-off: hash is paranoid for a
   just-written file; size+mtime covers the realistic disk-full/truncation failure.
8. **`boomtube config` output.** Resolved YAML (recommended) vs a plan preview incl. detected
   kinds and per-link warnings. Trade-off: YAML round-trips for scripting; preview is more
   informative but is a second format to maintain.
9. **`migrate` default (F17).** Confirm keeping `migrate: true` (recommended) — flipping to
   `false` would break first-run migration for existing configs that omit the field and would
   send them into F2 refusal territory.

---

## 9. Risks and trade-offs of the plan

- **Breaking changes for existing configs.** F1/F3/F4/F13/F16/F24 configs start failing
  validation; F2 configs start refusing; F10 conflict names change. Mitigation: every rejection
  message states the exact fix (move the link inside the project; add `--force`; rename the
  var); §6 README migration notes; the breaking set is precisely the set of data-loss/broken
  configs, so "kept working" is not a goal for them.
- **New complexity → new bugs.** Staging/verify/swap + two-pass merge + locking is the largest
  code change. Mitigation: phases are independently shippable with exit criteria; the
  crash-window and truncation simulations in the test plan target the new code directly;
  fallbacks defined (rename failure → refuse link, don't fall back to rmtree; no `fcntl` → skip
  lock, documented).
- **Lock contention / platform caveats.** Whole-run flock serializes concurrent applies (fine for
  a per-project tool) but is advisory: NFS flock semantics are unreliable and Windows has no
  `fcntl` (lock skipped there). Residual: two applies over NFS could still race — the
  verify-before-swap + atomic swap make the worst case a clean per-link failure, not corruption.
- **Performance.** Per-copy verification + snapshot re-hash add I/O proportional to the number of
  files; acceptable for typical dotfile/config trees, worth profiling for very large targets
  (open Q7 trades strength for speed if needed).
- **New risk spotted while designing (not in findings, not chased):** a link whose *parent* is a
  symlink created by an earlier link in the same run can escape the project root at apply time
  despite passing preflight (resolution uses pre-run state). Contained by I2 (apply-time geometry
  re-check after parent creation → per-link error, no escape). Listed here per the rules.
- **Adjacent hazard folded into scope:** `migrate_dir` can write *through* a symlink at a rel
  when one side has a real file at the same rel (copy2 follows dst symlinks). This is the same
  write-through class as F21, so the `_copy` guard is included in P2; flagged here as design-
  required rather than a new finding.
- **Scope creep.** The plan touches only modules the findings implicate (plus the two small new
  modules). `util.py`/`hashing.py` changes are limited to conflict naming and TOCTOU tolerance.
  Review gate: any change outside the listed task sets must be justified against a finding.

---

## Definition of done checklist (self-check)

- [x] Read code, README, findings report, repros; environment verified (typer 0.27.1 behavior,
  `commonpath`/`flock`/`Path("")` primitives confirmed live).
- [x] Every CRITICAL (F1–F4) and HIGH (F5–F9) finding has a design trace (§3) showing the failure
  mode is eliminated or exactly contained.
- [x] Every F1–F24 appears in the resolution table (§4), incl. INFO entries resolved as docs/no-change.
- [x] Phased plan (P0–P4), each phase shippable with tests and exit criteria, ordered so risk
  never increases (justified in §5).
- [x] All deliberate behavior changes flagged ("Behavior change? = Yes") with one-line rationale.
- [x] Open questions numbered, decision-ready, with recommendation + trade-off (§8).
