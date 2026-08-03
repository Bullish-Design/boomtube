# Refactoring Planning Session: Boomtube

Copy this prompt verbatim into a clean pi session, then hand it the repo.

---

## Your mission

You are a **senior engineer leading the refactoring plan** for Boomtube. A prior adversarial review found **4 CRITICAL data-loss bugs**, several HIGH correctness bugs, and a broken CLI. Your job is **not to fix anything** — it is to produce a detailed, decision-ready **refactoring plan**: architecture changes, per-finding resolutions, an ordered implementation sequence, a test plan, and a list of open questions.

Mindset:

- **The plan must eliminate each CRITICAL/HIGH finding by design, not by patch.** For every one, show *why* the proposed design makes the failure mode structurally impossible (or, if impossible, exactly how it is contained).
- **Every behavior change must be deliberate and flagged.** Some fixes require changing documented behavior (e.g., `migrate: false` currently destroys data). Call these out explicitly: what changes, who it affects, and what README text must be updated to match.
- **The plan must be phased and each phase independently shippable.** No phase may leave the tool *more* dangerous than the previous one.
- **Assume existing `boomtube.yaml` files must keep working** unless you explicitly justify a breaking change and add a migration story.
- Do not re-review the code from scratch. Treat the findings table below as the authoritative bug list. Re-derive details only when needed to make a design decision.
- **Do not edit any source, test, or config file.** Planning only.

## Context

Boomtube is a "project-local symlink manager with safe migration." `boomtube apply` (a) resolves variables, (b) optionally merges any real file/dir currently at the link location with the target ("migration"), and (c) replaces the link location with a symlink. It claims to be idempotent and safe (no data loss). The #1 threat class is **data loss**: it `rmtree`s directories, overwrites files by mtime, moves data between trees, and creates symlinks from config-controlled paths.

### Project layout

```
src/boomtube/
  models.py    # Pydantic config models + validation rules
  config.py    # YAML loading + error wrapping
  resolve.py   # Variable interpolation (DFS w/ cycle detection)
  fsops.py     # Path normalization, symlink/remove primitives
  hashing.py   # SHA-256 content comparison
  migrate.py   # File + directory bidirectional merge logic
  apply.py     # Orchestration: kind detection, symlink creation/replacement
  cli.py       # Typer CLI (exit codes 2/3/4)
  util.py      # Conflict naming, unique paths, stats
tests/         # ~27 tests, all passing (tautological; ignore for planning)
README.md      # Documents intended behavior (known to disagree with code)
pyproject.toml # Deps: pydantic, typer, pyyaml; requires Python >=3.13
```

## Inputs (read these first)

1. All of `src/boomtube/*.py`, `tests/*.py`, `README.md`, `pyproject.toml`.
2. The full adversarial findings report at `/tmp/btr/findings-report.md` if present (and the repro scripts `/tmp/btr/repro*.py`). If `/tmp/btr` is gone, the embedded table below is sufficient — do not redo the review.
3. Environment (if you need to verify current behavior — verify only, don't re-hunt):
   ```bash
   cd /home/andrew/Documents/Projects/boomtube
   /tmp/btenv/bin/python -m pytest          # suite is green; you can ignore results
   /tmp/btenv/bin/python -c "import boomtube"
   ```
   Do NOT use `devenv shell` (10+ min Nix). Write scratch scripts under `/tmp/` only.

## Findings to plan for (authoritative bug list)

Severity: **CRITICAL** = data loss / security, HIGH = wrong behavior on common input, MEDIUM = edge misbehavior, LOW = doc/UX.

| ID | Sev | Bug (short) | Key locations |
|----|-----|-------------|---------------|
| F1 | CRITICAL | `link: .notes`, `target: .notes/backup`: migration copies data into the backup, then `rmtree(.notes)` deletes the backup too → dangling symlink, data gone. Merge assumes A and B are disjoint trees. | apply.py:41-91, migrate.py:88-138, fsops.py:50 |
| F2 | CRITICAL | `migrate: false` (README's documented *default*) + non-empty real dir/file at link path → silent `rmtree`, no warning, target ends up empty. | apply.py:89, fsops.py:44-50 |
| F3 | CRITICAL | `link: ../outside` (or `a/../../b`) passes "relative" validation → `rmtree`/`symlink_to`/`mkdir` operate outside the project root; sibling user data destroyed. | models.py:23-33, apply.py:41 |
| F4 | CRITICAL | `link: "."`, `target: ""`: link path == project root; merge sees all-identical, then `rmtree(project_root)` deletes the entire project, reported as success. | apply.py:41,89; fsops.py:50 |
| F5 | HIGH | `{}` / stray braces in a var or target raise `ValueError` (not `KeyError`), escaping every `except KeyError` handler → raw traceback. | resolve.py:19-20,74-75; apply.py:42 |
| F6 | HIGH | Missing var in `target` → unhandled raw `KeyError` at apply time; discovered only at runtime, after earlier links already mutated. | apply.py:42 |
| F7 | HIGH | `boomtube apply` broken under typer 0.27.1 (what `typer>=0.12` resolves to today): single-command Typer apps auto-invoke, so `apply` becomes "unexpected extra argument". Only bare `boomtube` works. | cli.py:14-16, pyproject.toml:11 |
| F8 | HIGH | Kind misdetection: `kind: file` on a real dir → `IsADirectoryError`; `kind: dir` on a real file → `FileExistsError`; crash mid-run, nothing applied. | apply.py:74-76, migrate.py:53,91 |
| F9 | HIGH | Dir merge type collision (A has file `x`, B has dir `x/`): crash + partial merge state; also `copy2(file, existing_dir)` silently *nests* the file as `x/x` instead of failing. | migrate.py:102-110,15,19-20 |
| F10 | MEDIUM | Re-running migration duplicates and spreads `.conflict-from-project-*` files to both sides; README's "preserved on target" claim breaks on re-runs. | migrate.py:130-138, util.py:11-21 |
| F11 | MEDIUM | TOCTOU: file deleted between `exists()` and `stat()`/`sha256` → unhandled `FileNotFoundError`; partial state. Also the crash mode observed in concurrent applies (F14). | migrate.py:45-66, hashing.py:9-14, migrate.py:120 |
| F12 | MEDIUM | `apply_all` aborts at the first failing link; no per-link error reporting or success summary. | apply.py:94-96 |
| F13 | MEDIUM | Empty `target` accepted → symlink to the project root (recursion trap for any walker); with a real dir at link + migrate, whole project copied into link then rmtree'd. | models.py (no target validator), fsops.py:26-35, apply.py:43 |
| F14 | MEDIUM | Concurrent `apply` runs race: loser crashes mid-migration (`FileNotFoundError`); no locking; other interleavings could leave dangling links/partial trees. | migrate.py:120, apply.py:89 |
| F15 | LOW | No post-copy verification before deleting the source: disk-full mid-`copy2` → truncated destination, source deleted. (UNVERIFIED repro, structural risk.) | migrate.py:19-20, apply.py:89 |
| F16 | LOW | User `vars` can override `project_root`/`project_name` builtins (`{**builtins, **resolved_user}` order). | resolve.py:27-31 |
| F17 | LOW | README says `migrate` defaults to `false`; code defaults to `true`. Makes F2 reachable via README guidance. | models.py:19, README:116,158 |
| F18 | LOW | README documents a `boomtube config` command; CLI has only `apply`. | cli.py |
| F19 | LOW | README documents exit code 1 for failures; CLI uses 2/3/4. | cli.py:45-58 |
| F20 | LOW | FIFO at the link path → `shutil.SpecialFileError` crash (no hang; special files inside walked dirs are correctly filtered). | migrate.py:53 |
| F21 | LOW | Direct `migrate_file` on a broken symlink treats it as "missing" and writes *through* it to its target (apply flow itself is safe). | migrate.py:41-49 |
| F22 | INFO | Sub-ms mtime differences → spurious conflict files; direction logic itself is correct in all tested orderings. | migrate.py:11,71-76,123-128 |
| F23 | INFO | README claims var resolution is "topological sort"; code does DFS memoization (equivalent output). | resolve.py |
| F24 | INFO | `version: yes` accepted as version 1 (PyYAML 1.1 bool coercion). | config.py |

Known-safe (do not spend plan effort "fixing" these): apply-level second-run idempotency, `remove_path` on symlink-to-dir (correctly unlinks), broken-symlink handling in the apply flow.

## What the plan must decide (design questions, not code)

1. **Validation layer**: where does safety validation live (`models.py` field/model validators vs `config.py` vs a new pre-flight pass in `apply.py`)? Which checks are config-load-time (fail fast, exit 2) vs apply-time (per-link, context-dependent)? Proposed checks: link stays inside project root (F3); target != link and target not inside link tree and vice-versa (F1, F4); empty/`.` link and empty target rejected (F4, F13); link != project root.
2. **`migrate: false` semantics (F2)**: refuse-and-error, require an explicit destructive flag, or move-to-trash? This is a deliberate behavior change vs README — define the new contract and the README diff.
3. **Merge correctness (F1, F9, F10, F15)**: is a *disjoint-trees invariant* (reject overlapping roots up front) sufficient, or do you also need: type-collision detection per rel (file vs dir), conflict-file exclusion from `_list_files`, and post-copy verification (size or hash) before `remove_path`? Consider a staging/verify/swap sequence.
4. **Atomicity (F4, F11, F14)**: how to make "migrate → remove old → create symlink" crash-safe and race-safe: per-link lock vs whole-run lock (`flock`), temp-symlink + rename for the swap, tolerance for mid-flight file disappearance (skip vs abort).
5. **Template resolution (F5, F6)**: centralize template rendering so `KeyError`/`ValueError`/`IndexError` all become `VarResolutionError`; pre-resolve all targets during config load so errors are caught before any mutation.
6. **CLI (F7, F18, F19)**: restructure for the supported typer range (explicit subcommand layout or pinned dependency) so `boomtube apply` works; decide whether to add `boomtube config`; reconcile documented exit codes with actual codes.
7. **Failure handling (F8, F12)**: per-link try/except with continue, per-link exit reporting, and a final summary; typed internal errors for kind/type mismatches.
8. **Locking scope (F14)**: is a whole-run file lock acceptable (simpler) vs per-link locks (parallel-friendly)? State the trade-off and the residual risk if you recommend no locking.
9. **Docs (F17-F19, F23)**: list every README/exit-code/behavior claim that must change.

## Mandatory process

1. Read the code and inputs (above). Take notes on the current control flow: one paragraph per module, plus the full sequence of `apply_link` for (i) missing link, (ii) correct symlink, (iii) stale symlink, (iv) real file/dir with migrate, (v) real file/dir without migrate.
2. For each CRITICAL/HIGH finding, write a short **design trace**: current failure path → proposed design → why the failure is now impossible (or exactly how it's contained). This is the core of the plan.
3. Design the **phased sequence** (suggest: P0 safety validation, P1 data-loss fixes, P2 merge correctness, P3 CLI/robustness, P4 docs/tests — but justify your own ordering). For each phase: scope, modules touched, behavior changes, new tests, and what "done" means. No phase may increase risk vs the prior one.
4. Write the **test plan**: map every F# to the regression test(s) that would catch it (the existing `/tmp/btr/repro*.py` scripts are a head start), plus unit tests for new invariants (e.g., overlap rejection, conflict exclusion, atomic swap).
5. List **open questions** for the human (decisions you can't make unilaterally — e.g., trash vs refuse for F2, breaking `migrate` default for F17).
6. Deliver the plan (format below).

## Deliverables

### 1. Design summary
- Target architecture: one paragraph + a module-responsibility table (module → responsibility after refactor → notable new functions/invariants).
- The invariants the new design guarantees (e.g., "link and target trees are always disjoint", "no file is ever removed before its destination is verified", "templates are fully validated before any filesystem mutation").

### 2. Per-finding resolution table
| F# | Sev | Design decision | Module(s) | Behavior change? | Residual risk |

### 3. Phased implementation plan
For each phase: goal, tasks (function-level granularity), files touched, behavior changes, new/updated tests, exit criteria. Phases must be independently shippable and ordered so risk never increases.

### 4. Test plan
- New unit tests (per invariant).
- Regression tests mapped to F1-F24 (reuse repro scripts where possible).
- Any tests you'd delete or rewrite (e.g., tests that assert the buggy behavior).

### 5. Documentation update list
Every README claim that must change (F17, F18, F19, F23 + anything your design alters), with the replacement wording you'd propose.

### 6. Open questions
Numbered decisions needed from the human, each with your recommendation and the trade-off.

### 7. Risks and trade-offs
What could go wrong with the plan itself (e.g., behavior changes breaking existing users, lock contention, scope creep) and how to mitigate.

## Constraints

- **Do not modify any source, test, or config file.** Planning only — no code, no YAML edits, no README edits.
- Scope is exactly the findings table plus what your design requires. No unrelated refactors, no style churn, no rewriting sound modules for taste.
- Do not re-derive findings or re-hunt for new bugs; use the table as authoritative. If you spot a *new* risk while designing, list it under "Risks" — don't chase it.
- Keep every deliberate behavior change visible: each one must appear in the resolution table with "Behavior change? = Yes" and a one-line rationale.
- Prefer the simplest design that eliminates the failure class, over clever designs. Favor fail-fast validation over defensive recovery.

## Definition of done

1. You have read the code, README, and the findings report/repros (or embedded table).
2. Every CRITICAL and HIGH finding has a design trace showing the failure mode is eliminated or exactly contained.
3. Every finding F1-F24 appears in the resolution table (even if the resolution is "no change — documented behavior, downgrade").
4. The plan is phased, each phase shippable, with tests and exit criteria.
5. All deliberate behavior changes are flagged with a README-update note.
6. Open questions are explicit and decision-ready (recommendation + trade-off), not vague.
