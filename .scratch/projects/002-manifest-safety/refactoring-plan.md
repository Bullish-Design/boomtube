# Boomtube Refactoring Plan — 002 "manifest safety"

Status: **COMPLETE** — implemented in full. See `.scratch/projects/002-manifest-safety/decision-log.md`
for the open-decision resolutions (D1–D10). Final state: 225 tests passing, 96% coverage,
`ruff check src tests` clean, and both `repros/*.py` print `NOT CONFIRMED` for every finding.

Baseline: commit `50aed5a`, boomtube 0.2.0, suite green (159 passed, 96% coverage).
Inputs: full read of `src/boomtube/*.py`, `tests/*.py`, `README.md`, `pyproject.toml`, `devenv.nix`.
Evidence: `repros/verify_core_findings.py`, `repros/verify_cli_findings.py` — every finding below was
previously executed against the real package inside `devenv shell`; the repros now assert the
post-fix state and must print `NOT CONFIRMED` throughout.

---

## 0. The one-sentence diagnosis

**Every safety mechanism in the codebase is defined in terms of `snapshot_files()`, which silently
excludes symlinks, special files, empty directories, and conflict-named files — and then the atomic
swap `rmtree`s the whole tree anyway.**

The exclusions are correct for *"never follow or copy this"*. They are catastrophic for
*"therefore it need not be preserved"*. `_verify_snapshot_copied` cannot catch the gap, because the
snapshot it verifies against is the same snapshot that dropped the data.

Findings 1, 2 and 3 are three faces of that single defect. Fixing it is Steps 1–4 and is the
entire point of this plan. Everything after Step 4 is smaller, independent, and shippable
separately.

### What is *not* broken (do not regress these)

The design is sound and several invariants genuinely hold. Adversarial probing could not break:

- Regular files are never lost. `_verify_snapshot_copied` really does gate the swap.
- Preflight geometry (link escaping root, link == root, link/target overlap) is correctly enforced
  before any mutation, and correctly re-verified per link at apply time.
- `_swap`'s root/ancestor guard, the `os.replace`-based atomic symlink, and TOCTOU tolerance for
  vanished files all work as documented.
- Size-based (not `st_mtime`) copy verification is the right call and is correctly implemented.

Preserve all of the above. This plan widens the definition of "content"; it does not weaken any
existing check.

---

## 1. Findings table

Severity: **C**ritical (silent unrecoverable data loss) / **H**igh (silent wrong state) /
**M**edium / **L**ow.

| # | Sev | Finding | Location | Step |
|---|-----|---------|----------|------|
| 1 | C | Symlinks, special files, empty dirs, and `*.conflict-from-project-*` files inside a migrated directory are deleted, never copied. Target ends **empty**, exit 0. | `migrate.py:58` `snapshot_files`, `apply.py:88`, `apply.py:121` | 1–2 |
| 2 | C | `migrate: false` deletes that same content with **no `--force`**, contradicting the README guarantee. | `migrate.py:90` `has_real_content` | 3 |
| 3 | H | Crash residue holding the only copy is `rmtree`d on the next run; the "always redundant" docstring inherits the same hole, and is simply false for the `migrate: false` path (which calls `_swap` with no seeding at all). | `fsops.py:59` | 4 |
| 4 | H | Repointing an existing symlink skips `_ensure_target` → dangling symlink, exit 0. Triggered by editing `target:` in `boomtube.yaml`. | `apply.py:151` | 5 |
| 5 | H | No cross-link preflight: duplicate `link` paths and nested targets both accepted. Second link silently breaks the first. | `planning.py:55` | 6 |
| 6 | M | `reclaim_staging_residue` interpolates `path.name` into a glob unescaped → a link named `[mn]` deletes sibling `n.bt-staging-*`. | `fsops.py:66` | 4 |
| 7 | M | Exit codes 3 and 4 are unreachable; real `PermissionError` during apply reports 5, unreadable config reports 2. Tests "cover" them only via monkeypatch. | `cli.py:80`, `config.py:21`, `apply.py:231` | 7 |
| 8 | M | `--config` silently discards an explicitly-passed `--project-root`. | `cli.py:32` | 7 |
| 9 | M | Pydantic `extra="ignore"` → `migrat: false` typo accepted, migration stays **on**. | `models.py:12,59` | 8 |
| 10 | L | `detect_kind` dot-heuristic tests the whole link string: `.nvim`→`dir` but `config/.nvim`→`file`. | `apply.py:56` | 9 |
| 11 | L | Type-collision pre-scan misses target-side symlinks → partial copies land in target despite the "zero partial state" claim. | `migrate.py:100` `_type_map` | 2 |
| 12 | L | `_verify_snapshot_copied` uses `dst.is_file()`, which follows symlinks — a target symlink satisfies verification for a link-side regular file. | `apply.py:98` | 2 |
| 13 | L | Fresh `kind: file` link with no existing target produces a dangling symlink, silently. | `apply.py:81` `_ensure_target` | 5 |
| 14 | L | `--force` sweeps target-only files that collide with nothing into conflict names. | `migrate.py:258` | 2 (decision) |
| 15 | L | `link:` containing a NUL byte passes validation, raises uncaught `ValueError` from `.resolve()`. | `models.py:21` | 9 |
| 16 | L | Redundant work: 4 tree walks per dir link; `files_identical` always hashes both files fully. | `apply.py:189`, `migrate.py:236,240` | 2, 10 |
| 17 | L | Dead code: `MigrationStats.copied_b_to_a`, `resolve.render`, `LinkSpec.kind_allowed`, triple `reclaim_staging_residue` call. | various | 10 |
| 18 | L | Hardlinked files in a migrated tree are copied as independent files, breaking the link. | `migrate.py:27` | 10 (doc) |
| E1 | — | `devenv.nix` had `venv.enable` + `uv.enable`, creating a dependency-free venv that shadowed uv's. **Already fixed** this session. | `devenv.nix` | done |
| E2 | — | `uv.lock` is gitignored (`.gitignore:12`) while that file's own comment recommends committing it. | `.gitignore` | 11 |
| E3 | — | `devenv.cachix.org` missing from nix substituters → devenv's Rust binaries build from source (~15 min). | system config | 11 |

---

## 2. Sequencing and risk

```
Step 0  characterization tests (RED)        ── no behavior change, safe to land alone
  │
  ├─ Step 1  Manifest core (new scan_tree)  ── additive; nothing calls it yet
  │    └─ Step 2  seed_dir + verify rewrite ── THE critical change
  │         └─ Step 3  has_real_content     ── depends on Step 1
  │              └─ Step 4  reclaim safety  ── depends on Step 2's verifier
  │
  ├─ Step 5  symlink branch / _ensure_target ── independent
  ├─ Step 6  cross-link preflight            ── independent
  ├─ Step 7  CLI exit codes + project root   ── independent
  ├─ Step 8  models extra=forbid             ── independent
  ├─ Step 9  detect_kind + validators        ── independent
  └─ Step 10 dead code + perf                ── independent
       └─ Step 11 docs + repo/env hygiene    ── last, documents the new semantics
```

Steps 5–10 are each self-contained and can land in any order, before or after the 1–4 chain.
If you want the highest safety-per-diff first, land **Step 8 and Step 6** immediately (tiny,
pure-refusal, zero regression risk), then commit to the 1–4 chain.

Run `devenv shell -- uv run pytest -q` after every step. Note `pytest` bare will not work — see
Step 11.

---

## Step 0 — Characterization tests (do this first)

**Goal:** turn all 10 confirmed findings into failing tests before changing any behavior, so the
refactor is provably driven by them and regressions are impossible to miss.

**Files:** `tests/test_data_preservation.py` (new), `tests/test_planning.py`,
`tests/test_cli.py`, `tests/test_config.py`.

Port `repros/verify_core_findings.py` and `repros/verify_cli_findings.py` into real tests. Each
asserts the **desired post-refactor** behavior, so all are RED at the start:

```python
def test_symlink_inside_migrated_dir_is_preserved(tmp_path):
    # F1 — currently: target is empty and the symlink is destroyed
    ...
    assert (target / "ln-to-real").is_symlink()
    assert os.readlink(target / "ln-to-real") == str(outside / "real.txt")

def test_empty_subdir_is_preserved(tmp_path): ...
def test_conflict_named_user_file_is_preserved(tmp_path): ...
def test_special_file_inside_tree_is_refused(tmp_path): ...   # refusal, not silent loss
def test_migrate_false_refuses_dir_of_symlinks(tmp_path): ... # F2
def test_repointing_symlink_creates_target(tmp_path): ...     # F4
def test_duplicate_link_paths_rejected_at_preflight(tmp_path): ...  # F5a
def test_nested_targets_rejected_at_preflight(tmp_path): ...        # F5b
def test_reclaim_glob_metachars_escaped(tmp_path): ...              # F6
def test_permission_error_during_apply_exits_3(tmp_path): ...       # F7
def test_explicit_project_root_wins_over_config_parent(tmp_path): ...# F8
def test_unknown_link_field_rejected(): ...                          # F9
def test_detect_kind_uses_basename(): ...                            # F10
```

**Delete** `tests/test_cli.py::test_oserror_maps_to_exit_4` and
`::test_permission_error_maps_to_exit_3`. They monkeypatch `build_plan` to raise, which real code
never does — they assert the `except` clauses are syntactically present, not that anything reaches
them. Replace with the real-cause tests above.

**Also delete** the two `assert stats.copied_b_to_a == 0` lines
(`tests/test_migrate_dirs.py:29`, `tests/test_migrate_files.py:18`) — they assert a field that is
never written.

**Exit criteria:** 13 new tests, all failing for the documented reason. Suite otherwise green.

---

## Step 1 — Manifest core

**Goal:** one function that describes *everything* in a tree, with no lossy exclusions.
Purely additive — no existing caller changes in this step.

**File:** `src/boomtube/migrate.py`

```python
EntryKind = Literal["file", "dir", "symlink", "special"]

@dataclass(frozen=True)
class Entry:
    rel: str
    kind: EntryKind
    size: int | None = None          # regular files only
    link_target: str | None = None   # symlinks only — RAW, un-resolved

@dataclass(frozen=True)
class Manifest:
    root: Path                        # the *resolved* root the rels are relative to
    entries: dict[str, Entry]

    def of_kind(self, kind: EntryKind) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind == kind]

    @property
    def is_empty(self) -> bool:
        return not self.entries


def scan_tree(root: Path, *, exclude_conflicts: bool = False) -> Manifest:
    """Full inventory of `root`. Symlinks are RECORDED but never followed."""
```

Implementation notes that matter:

1. **A symlinked root still returns an empty manifest.** Preserves the existing F21 guarantee
   (`test_snapshot_of_symlink_root_is_empty`).
2. **`os.walk` splits symlinks across both lists**: symlink-to-directory appears in `dirnames`,
   symlink-to-file and broken symlinks in `filenames`. Handle both. Today's code filters symlinked
   dirs out of `dirnames` and drops them entirely — the new code must filter them from *descent*
   while still *recording* them.
3. **`exclude_conflicts` is target-side only.** This is the fix for the conflict-named-file half
   of F1: today `snapshot_files` applies the filter unconditionally, so a user's own
   `foo.conflict-from-project-ab12` under the link path is invisible and gets deleted.
4. **Empty directories are recorded**, which `snapshot_files` never did.
5. **TOCTOU:** wrap `p.stat()` / `os.readlink(p)` in `try/except (FileNotFoundError, OSError)` and
   skip — matches existing F11 behavior.
6. Store the **resolved** root on the Manifest so `manifest.root / rel` is always well-defined.

Keep `snapshot_files` as a thin deprecated shim during the transition:

```python
def snapshot_files(root: Path) -> dict[str, Path]:
    mf = scan_tree(root, exclude_conflicts=True)
    return {e.rel: mf.root / e.rel for e in mf.of_kind("file")}
```

so `tests/test_migrate_dirs.py`'s existing snapshot tests keep passing while Step 2 lands. Delete
it in Step 10.

**Tests:** `tests/test_manifest.py` (new) — a fixture tree containing a regular file, a nested
regular file, an empty dir, a dir symlink, a file symlink, a broken symlink, a FIFO, and a
conflict-named file. Assert exact `Entry` kinds; assert `exclude_conflicts` toggles only the
conflict entry; assert a symlinked root yields empty; assert no descent through the dir symlink.

**Exit criteria:** new tests green, existing suite still green (nothing calls `scan_tree` yet).

---

## Step 2 — Rewrite `seed_dir` and the verifier around the manifest

**Goal:** close F1, F11, F12. This is the critical change.

**Files:** `src/boomtube/migrate.py`, `src/boomtube/apply.py`

### 2a. Refuse special files before any mutation

Move the `UnsupportedLinkTypeError` check (today only at the link *root*, `apply.py:159`) to cover
the whole tree. In `seed_dir`, immediately after scanning:

```python
link_mf = scan_tree(link_dir, exclude_conflicts=False)   # link side: exclude NOTHING
specials = link_mf.of_kind("special")
if specials:
    raise UnsupportedLinkTypeError(
        f"link tree {link_dir} contains special file(s) (FIFO/socket/device) that cannot be "
        f"migrated: {', '.join(e.rel for e in specials[:5])}; move or delete them first"
    )
```

A refusal is correct here. Silently deleting a FIFO is the current behavior and is indefensible;
copying one is meaningless. `UnsupportedLinkTypeError` must move to `migrate.py` (or a shared
`errors.py`) to avoid an `apply → migrate` import cycle.

### 2b. Collision scan over all four kinds

Delete `_type_map` entirely; derive collisions from the two manifests. This also fixes **F11**
(target-side symlinks were invisible to `_type_map`, so a collision was discovered mid-copy after
partial state had landed):

```python
def _check_type_collisions(link_mf: Manifest, target_mf: Manifest) -> None:
    for rel in sorted(set(link_mf.entries) & set(target_mf.entries)):
        a, b = link_mf.entries[rel].kind, target_mf.entries[rel].kind
        if a != b:
            raise MigrateCollisionError(...)
```

Note the behavior change: `target_mf` now includes symlinks and empty dirs, so a target containing
*only* symlinks now counts as populated and triggers the both-populated refusal. That is more
conservative and correct — call it out in the README (Step 11).

### 2c. Ordered materialization

Replace the flat file loop. Order matters — dirs before files, symlinks last so their parents exist:

```python
# 1. directories, shallowest first (recreates EMPTY dirs — F1)
for e in sorted(link_mf.of_kind("dir"), key=lambda e: e.rel.count(os.sep)):
    dst = target_dir / e.rel
    dst.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        shutil.copystat(link_mf.root / e.rel, dst)   # best effort: mode/mtime
    stats.dirs_created += 1

# 2. regular files — unchanged _copy(), still size-verified
for e in sorted(link_mf.of_kind("file"), key=lambda e: e.rel):
    ...existing identical-skip + _copy() logic...

# 3. symlinks last
for e in sorted(link_mf.of_kind("symlink"), key=lambda e: e.rel):
    _copy_symlink(target_dir / e.rel, e.link_target)
    stats.symlinks_copied += 1
```

```python
def _copy_symlink(dst: Path, raw_target: str) -> None:
    """Recreate a symlink verbatim. The raw target is preserved, so relative
    symlinks stay relative — resolving them here would silently rewrite them."""
    t = sniff_type(dst)
    if t == "symlink":
        if os.readlink(dst) == raw_target:
            return                       # already correct — idempotent re-run
        dst.unlink()
    elif t in ("file", "dir"):
        raise MigrateCollisionError(f"refusing to replace existing {t} with symlink: {dst}")
    _ensure_parent(dst)
    os.symlink(raw_target, dst)
```

Preserving the **raw** link target is the important part. Resolving it would turn a relative
intra-tree symlink into an absolute path pointing back at the soon-to-be-deleted staging tree.

### 2d. Conflict sweep must handle symlinks

`_move_aside_conflict` hashes file content; a symlink has none. `sha256(path)` would follow it.

```python
def _content_key(path: Path) -> str:
    if sniff_type(path) == "symlink":
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    return sha256(path)
```

Scope the sweep to files and symlinks; leave target-side directories alone (a dir at a rel where
the link also has a dir is a merge, not a conflict).

### 2e. Manifest-aware verifier

Replace `apply.py:_verify_snapshot_copied` wholesale. This also fixes **F12** — the old version
used `dst.is_file()`, which follows symlinks, so a target-side symlink satisfied verification for a
link-side regular file:

```python
def _verify_manifest_migrated(link_mf: Manifest, target_dir: Path, display: str) -> None:
    for rel in sorted(link_mf.entries):
        e = link_mf.entries[rel]
        src, dst = link_mf.root / rel, target_dir / rel
        if sniff_type(src) == "missing":
            continue                                  # vanished mid-run (F11)
        t = sniff_type(dst)                           # lstat — does NOT follow
        if e.kind == "file":
            if t != "file" or dst.stat().st_size != src.stat().st_size:
                raise CopyVerificationError(...)
        elif e.kind == "dir":
            if t != "dir":
                raise CopyVerificationError(...)
        elif e.kind == "symlink":
            if t != "symlink" or os.readlink(dst) != os.readlink(src):
                raise CopyVerificationError(...)
        else:
            raise CopyVerificationError(f"special file {src} reached verification")  # unreachable
```

Call it from `apply_link` in place of `_verify_snapshot_copied`, passing the manifest `seed_dir`
already built (see 2f).

### 2f. Stop re-walking (F16)

`apply.py:189` calls `snapshot_files`, then `seed_dir` scans again, then `_type_map` scans twice
more — 4 walks per dir link. Have `seed_dir` return its manifest alongside stats:

```python
stats, link_mf = seed_dir(link_path, target_path, force=force)
_verify_manifest_migrated(link_mf, target_path, display)
```

### 2g. Decision required — F14 sweep scope

Today `--force` renames **every** target-side file aside, including files that collide with
nothing (confirmed: `untouched-by-project.txt.conflict-from-project-9b76e1be`). Two options:

- **(a) Keep** — target side is wholly "preserved but demoted"; matches the current README wording.
- **(b) Scope to colliding rels** — non-colliding target files stay in place and the merged tree is
  a union; log the ones left alone.

(b) is far less alarming and is what a user reading "conflict file" expects. **This is a product
call — pick one before implementing 2d.** Data is preserved either way.

**Tests:** all of Step 0's F1 tests turn GREEN. Add: relative symlink stays relative; broken
symlink is preserved; nested empty dir chain `a/b/c/` recreated; dir mode preserved; re-running a
completed migration is a no-op (idempotency); FIFO nested three levels deep is refused with the
path in the message.

**Exit criteria:** F1, F11, F12 tests green. `test_inner_symlinks_are_ignored`
(`tests/test_migrate_dirs.py:99`) **must be rewritten** — it currently asserts
`not (target/"linkdir"/"secret.txt").exists()`, which stays true (we don't follow), but should now
also assert `(target/"linkdir").is_symlink()`. Its name is now wrong; rename to
`test_inner_symlinks_are_copied_not_followed`.

---

## Step 3 — `has_real_content` (F2)

**File:** `src/boomtube/migrate.py`

```python
def has_real_content(path: Path) -> bool:
    """True if `path` holds anything at all. Only a truly empty directory is 'no content'."""
    t = sniff_type(path)
    if t == "file":
        return True
    if t == "dir":
        with os.scandir(path) as it:
            return any(True for _ in it)
    return False
```

`os.scandir` does not follow symlinks and short-circuits on the first entry — cheaper *and* correct.

Behavior change: a directory containing only symlinks, only empty subdirs, or only conflict-named
files now requires `--force` under `migrate: false`. That is exactly the README's stated guarantee,
which currently does not hold.

**Tests:** existing `test_migrate_dirs.py:303-311` assertions still hold (truly-empty is still
`False`, a file is still `True`). Add: dir-of-symlinks is `True`; dir-with-empty-subdir is `True`;
dir-with-only-conflict-file is `True`.

---

## Step 4 — Reclaim safety + glob escaping (F3, F6)

**File:** `src/boomtube/fsops.py`

Two independent bugs in one function.

```python
def reclaim_staging_residue(path: Path, *, verified_against: Path | None = None) -> None:
    """Reclaim `<name>.bt-staging-*` / `.bt-tmp-*` crash residue.

    A staging tree is only redundant if its contents are provably present in the
    target. Anything unverifiable is quarantined as `.bt-orphan-*`, which is
    deliberately NOT matched by these globs, so it is never auto-deleted.
    """
    for suffix in (".bt-staging-*", ".bt-tmp-*"):
        for stale in path.parent.glob(glob.escape(path.name) + suffix):   # F6
            if stale.is_symlink() or stale.is_file():
                remove_path(stale)          # .bt-tmp-* symlinks are always redundant
                continue
            if verified_against is not None and _tree_is_covered_by(stale, verified_against):
                remove_path(stale)
                continue
            orphan = unique_path(stale.with_name(f"{path.name}.bt-orphan"))
            os.replace(stale, orphan)
            logger.warning(
                "preserved unverified crash residue as %s — inspect and remove manually", orphan
            )
```

`_tree_is_covered_by(stale, target)` is `_verify_manifest_migrated` returning a bool instead of
raising — factor the predicate out in Step 2 and reuse it. This is why Step 4 depends on Step 2.

Call sites:
- `apply.py:140` → `reclaim_staging_residue(link_path, verified_against=target_path)`
- `apply.py:112` (inside `_swap`) → **delete**; `rename_aside` already calls it
- `fsops.py:99` (inside `rename_aside`) → keep, pass the target through

For the `migrate: false` path, pass `verified_against=None` — nothing was ever seeded, so residue
is *never* provably redundant and must always be quarantined.

Also fix the docstring: the current claim ("always redundant") is false for `migrate: false`, which
reaches `_swap` with no seeding at all.

**Tests:** `tests/test_fsops.py` — residue whose contents are in the target is removed; residue with
an extra file is quarantined as `.bt-orphan` and *survives a second call*; a link named `[mn]` does
not touch `n.bt-staging-999`; `.bt-orphan-*` is never matched by the reclaim globs.

---

## Step 5 — Symlink branch and target creation (F4, F13)

**File:** `src/boomtube/apply.py`

```python
if link_type == "symlink":
    kind = detect_kind(spec, link_path, target_path, consult_link=False)
    _ensure_target(kind, target_path)                      # F4 — was missing entirely
    if _same_target(link_path, target_path):
        logger.info("ok (already correct): %s", display)
        return
    previous = None
    with contextlib.suppress(OSError):
        previous = readlink_abs(link_path)
    atomic_symlink(link_path, target_path)
    logger.warning(
        "repointed '%s': %s -> %s; the previous target was left untouched and is not migrated",
        display, previous, target_path,
    )
    return
```

`consult_link=False` is a new `detect_kind` parameter (Step 9). It matters: `link_path.exists()`
follows the symlink, so for a dangling link it returns `False` and for a live one it reports the
*target's* type — neither is what we want when deciding what to create.

**F13** — a fresh `kind: file` link whose target does not exist still produces a dangling symlink.
Do **not** auto-create an empty file (that masks config typos and litters targets). Instead collect
dangling results and report once at end of run:

```python
# in apply_plan, after the loop
dangling = [p for p in result.applied if p.is_symlink() and not p.exists()]
if dangling:
    logger.warning("%d symlink(s) point at paths that do not exist yet: %s",
                   len(dangling), ", ".join(str(p) for p in dangling[:5]))
```

This is a warning, not a failure — a dangling file symlink is legitimate for `.env.local`-style
links the user is about to populate.

**Tests:** repointing creates the new target dir; repointing logs a warning naming the old target;
an already-correct symlink whose target dir was deleted is recreated; dangling links are reported
but exit stays 0.

---

## Step 6 — Cross-link preflight validation (F5)

**File:** `src/boomtube/planning.py`

Add after the per-link loop in `build_plan`. Reuses the existing `_same_path` / `_strictly_inside`
helpers, so it inherits their casefolding.

```python
def _validate_pairwise(planned: list[PlannedLink]) -> None:
    for attr, label in (("link_path", "link"), ("target_path", "target")):
        seen: dict[str, PlannedLink] = {}
        for pl in planned:
            key = _casefold(getattr(pl, attr))
            if key in seen:
                raise PlanError(
                    f"duplicate {label} path {getattr(pl, attr)} used by both "
                    f"'{seen[key].spec.name or seen[key].spec.link}' and "
                    f"'{pl.spec.name or pl.spec.link}'"
                )
            seen[key] = pl

    for i, a in enumerate(planned):
        for b in planned[i + 1:]:
            for (pa, la), (pb, lb) in (
                ((a.link_path, "link"), (b.link_path, "link")),
                ((a.target_path, "target"), (b.target_path, "target")),
                ((a.link_path, "link"), (b.target_path, "target")),
                ((a.target_path, "target"), (b.link_path, "link")),
            ):
                if _strictly_inside(pa, pb) or _strictly_inside(pb, pa):
                    raise PlanError(
                        f"'{a.spec.name or a.spec.link}' {la} ({pa}) and "
                        f"'{b.spec.name or b.spec.link}' {lb} ({pb}) are nested; "
                        "links and targets must be pairwise disjoint"
                    )
```

O(n²) is fine — configs are tens of links, and this runs once before any mutation.

This is the highest safety-per-line change in the plan: both F5 failure modes become exit 2 with a
message naming both offending links, before anything is touched.

**Tests:** duplicate link → exit 2; duplicate target → exit 2; nested targets `T/sub` + `T` →
exit 2; link nested under another link → exit 2; link nested under another's target → exit 2;
two genuinely disjoint links still plan fine.

---

## Step 7 — CLI: exit codes and project root (F7, F8)

**Files:** `src/boomtube/cli.py`, `src/boomtube/config.py`, `src/boomtube/migrate.py`

### 7a. Make 3 and 4 reachable

`CopyVerificationError` currently subclasses `OSError`, which would misclassify a boomtube-level
refusal as an I/O error. Change it to `RuntimeError` first:

```python
class CopyVerificationError(RuntimeError):   # was OSError
```

Then classify the per-link failures:

```python
def _exit_code_for(failures: Sequence[tuple[Path, Exception]]) -> int:
    if any(isinstance(e, PermissionError) for _, e in failures):
        return 3
    if any(isinstance(e, OSError) for _, e in failures):
        return 4
    return 5
```

and in `config.py`, let `PermissionError` through instead of flattening it into `ConfigError`:

```python
except PermissionError:
    raise                                    # CLI maps to exit 3
except OSError as e:
    raise ConfigError(f"Unable to read config: {config_path}: {e}") from e
```

Document the precedence (3 > 4 > 5) in the README — with multiple failures the most specific wins.

### 7b. Honor an explicit `--project-root` (F8)

Also fixes the `Path.cwd()`-evaluated-at-import default.

```python
project_root: Path | None = typer.Option(None, "--project-root", help="Project root (default: cwd)")

def _resolve_project_and_config(project_root: Path | None, config: Path | None) -> tuple[Path, Path]:
    if config is not None:
        config_path = config.expanduser().resolve(strict=False)
        root = (project_root.expanduser().resolve(strict=False)
                if project_root is not None else config_path.parent)
        return root, config_path
    root = (project_root or Path.cwd()).expanduser().resolve(strict=False)
    return root, root / "boomtube.yaml"
```

Apply to **both** `apply` and `config` commands.

**Tests:** real `PermissionError` during apply (chmod 000 on a target parent) → exit 3; unreadable
config → exit 3; a plain per-link refusal → still 5; `--project-root A --config B/boomtube.yaml`
creates the link in **A**; `--config` alone still roots at the config's parent.

---

## Step 8 — Reject unknown config keys (F9)

**File:** `src/boomtube/models.py`

```python
from pydantic import ConfigDict

class LinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

class BoomtubeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

Two lines, and it closes a path where a typo (`migrat: false`) silently selects the *more*
destructive behavior. Land this early and independently.

**Tests:** `migrat: false` → `ConfigError`; unknown top-level key → `ConfigError`; the error message
names the offending key; every example config in the README still validates.

---

## Step 9 — `detect_kind` and validator hardening (F10, F15)

**Files:** `src/boomtube/apply.py`, `src/boomtube/models.py`

```python
def detect_kind(spec, link_path, target_path, *, consult_link: bool = True) -> str:
    if spec.kind in {"file", "dir"}:
        return spec.kind
    if consult_link and link_path.exists():
        return "dir" if link_path.is_dir() else "file"
    if target_path.exists():
        return "dir" if target_path.is_dir() else "file"
    p = Path(spec.link)
    if p.name.startswith(".") and p.suffix == "":     # F10: was spec.link.startswith(".")
        return "dir"
    return "file"
```

F15 — add NUL rejection to both validators (a NUL in `link` currently escapes model validation and
raises an uncaught `ValueError` from `.resolve()` deep in `build_plan`):

```python
if "\0" in v:
    raise ValueError("must not contain NUL bytes")
```

Also switch `util.unique_path` from `path.exists()` to `os.path.lexists(path)` so a dangling
symlink at the candidate path counts as taken.

**Tests:** `config/.nvim` → `dir`; `.nvim` → `dir`; `config/notes` → `file`; NUL in link/target →
exit 2 not traceback; `unique_path` skips a dangling symlink.

---

## Step 10 — Dead code and cheap performance (F16, F17, F18)

**Files:** `util.py`, `resolve.py`, `models.py`, `migrate.py`, `hashing.py`

- Delete `MigrationStats.copied_b_to_a` — vestige of the abandoned bidirectional design
  (see memory `boomtube-migration-model`). Add `dirs_created` / `symlinks_copied` from Step 2.
- Delete `resolve.render` (pass-through alias for `render_template`). Update `test_resolve.py:59`.
- Delete `LinkSpec.kind_allowed` — unreachable; the `Kind` Literal rejects bad values first.
- Delete the now-shim `snapshot_files` and `_type_map`; update `tests/test_migrate_dirs.py`
  snapshot tests to use `scan_tree`.
- `_files_identical`: short-circuit on the first differing block instead of hashing both files end
  to end. Sizes are already compared first, so this only helps the same-size-different-content case
  — which is precisely the `--force` conflict path.
- `atomic_symlink`'s `finally` catches only `FileNotFoundError`; a `PermissionError` from
  `tmp.unlink()` would mask the real exception. Broaden to `except OSError: pass`.
- Document the hardlink caveat (F18) in the migration section — hardlinked files are copied as
  independent files and the link relationship is not preserved.

---

## Step 11 — Documentation and repo/environment hygiene

**Files:** `README.md`, `.gitignore`, `devenv.nix` (done), system nix config

### 11a. README corrections — these are wrong *today*

| Section | Current claim | Reality |
|---|---|---|
| Safety guarantees | "Every file in the pre-seed snapshot … must have a verified copy" | True but vacuous — the snapshot excluded the data. Restate in terms of the manifest. |
| Directory Migration §5 | "Symlinks and special files inside the trees are skipped, never followed" | Reads as "left alone"; they were `rmtree`d. After Step 2: symlinks are **copied verbatim, never followed**; special files are **refused**. |
| Safety guarantees | "`migrate: false` never deletes non-empty real content without an explicit `--force`" | Did not hold (F2). Holds after Step 3. |
| Exit Codes | `3: Permission error`, `4: I/O error` | Unreachable until Step 7. Document 3 > 4 > 5 precedence. |
| Development | `pytest`, `ruff check src tests` | Bare `pytest` fails in-shell — see 11c. |
| Migration Behavior | — | **New:** empty directories are recreated; a target containing only symlinks now counts as populated. |

### 11b. `uv.lock` (E2)

`uv sync` generates a 59k `uv.lock`, but `.gitignore:12` excludes it — while that same file's own
boilerplate at line 110 says *"it is generally recommended to include uv.lock in version control."*
Now that uv owns the venv, that lock is the reproducibility guarantee. Remove line 12 and commit
`uv.lock`. (`cairn` on this machine commits its 95k lock.) **Repo-policy call — not done here.**

### 11c. devenv (E1 done, E3 open)

`devenv.nix` is already fixed this session: `venv.enable` removed, `uv.sync.enable` +
`extras = [ "dev" ]` added, `env.VIRTUAL_ENV` set. Verified from `rm -rf .devenv/state/venv`:
159 tests, exit 0.

Still open:

- **Invocation is `uv run`, not bare `pytest`.** Even with `VIRTUAL_ENV` set, `which python`
  resolves to the nix-store interpreter and `pytest` is not on `PATH` — `cairn` behaves identically,
  so this is the house pattern, not a boomtube defect. Update README to `devenv shell -- uv run pytest`.
  If you would rather bare `pytest` worked, add `export PATH="$UV_PROJECT_ENVIRONMENT/bin:$PATH"`
  to `enterShell` (the `image-gen-pipeline` approach) — **your call**.
- **E3 — add devenv's cache** (system-level, needs a rebuild):
  ```nix
  nix.settings = {
    substituters = [ "https://devenv.cachix.org" ];
    trusted-public-keys = [ "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw=" ];
  };
  ```
  Without it, devenv's own Rust binaries build from source (~15 min, observed). The artifacts are in
  the store now, so this only bites again on the next `devenv update`.
- `devenv 2.1.2 is newer than devenv input (1.11.2) in devenv.lock` → run `devenv update`.

---

## 3. Open decisions (need your call before implementing)

1. **F14 / Step 2g — `--force` sweep scope.** Sweep the whole target side (status quo) or only
   colliding rels? Affects README semantics.
2. **F13 / Step 5 — dangling file symlinks.** Warn at end of run (proposed), fail the link, or
   create an empty target file?
3. **E2 / Step 11b — commit `uv.lock`?** Recommended, but it is a repo-policy call.
4. **Step 11c — bare `pytest` on `PATH`?** House pattern says `uv run`; `image-gen-pipeline`
   disagrees.
5. **Step 2a — special files: refuse or skip-with-warning?** Refusal is proposed. Skipping would
   preserve today's ability to migrate a tree that happens to contain a socket, at the cost of
   silently not preserving it.

---

## 4. Definition of done

- [x] All 13 Step-0 characterization tests green.
- [x] `devenv shell -- uv run pytest -q` → exit 0, coverage ≥ 96% (225 passed, 96%).
- [x] `devenv shell -- uv run ruff check src tests` clean.
- [x] `repros/verify_core_findings.py` (7 findings) and `repros/verify_cli_findings.py` (5 findings)
      all print `NOT CONFIRMED`.
- [x] A directory containing only symlinks, only empty dirs, or only conflict-named files
      survives a migration with its structure intact.
- [x] `migrate: false` refuses on any non-empty link path without `--force`.
- [x] Every README safety guarantee in §11a is literally true of the code.
- [x] No `.bt-staging-*` tree is ever deleted without its contents being verified in the target.
