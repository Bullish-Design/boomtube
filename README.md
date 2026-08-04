# README.md

# Boomtube

Project-local symlink manager with safe migration

## Overview

Boomtube manages symlinks within your project directories using a declarative YAML configuration. It safely migrates existing files and directories when creating new symlinks, ensuring no data loss through validated, verified, atomic operations.

## Features

### Core Capabilities

- **Declarative Configuration**: Define all project symlinks in a single `boomtube.yaml` file
- **Safe Migration**: Automatically migrate existing files/directories before creating symlinks
- **One-Directional Migration**: Migration copies **link → target only**; the target is never copied back into the project. At steady state the symlink is the single source of truth
- **Conflict Protection**: If both the link path and the target hold real content, `apply` refuses (exit 5) unless you pass `--force`, which preserves the target side as conflict files
- **Variable Interpolation**: Use variables in target paths with built-in and custom variables
- **Automatic Kind Detection**: Intelligently detects whether to create file or directory symlinks
- **Idempotent Operations**: Safe to run multiple times without side effects

### Migration Strategy

Boomtube uses a validated, verified migration strategy:

- **Preflight validation**: every target is rendered and every path checked *before anything is touched*; unsafe configs are rejected with exit 2 and zero filesystem changes
- **One-way seed**: existing content at the link path is copied to the target (never the reverse)
- **Verified copies**: every copy is size-verified before its source can be removed
- **Content Hashing**: SHA-256 detects identical content to avoid redundant copies and to name conflict files deterministically
- **Conflict Preservation**: `--force` moves the target side aside as `.conflict-from-project-*` files (deterministic names), then seeds from the link side

## Installation

### Prerequisites

- Python 3.13 or later
- [UV](https://github.com/astral-sh/uv) for dependency management

### Install from Source

```bash
git clone https://github.com/Bullish-Design/boomtube
cd boomtube
uv pip install -e .
```

### Install with Development Dependencies

```bash
uv pip install -e ".[dev]"
```

## Quick Start

### 1. Create Configuration File

Create `boomtube.yaml` in your project root:

```yaml
version: 1

vars:
  notes_root: "~/Documents/Notes"
  data_dir: "/mnt/data"

links:
  - name: Project Notes
    link: ".notes"
    target: "{notes_root}/Projects/{project_name}"
    kind: dir
    migrate: true

  - name: Local Config
    link: ".env.local"
    target: "{data_dir}/configs/{project_name}.env"
    kind: file
    migrate: true
```

### 2. Apply Symlinks

```bash
boomtube apply
```

This will:
- Validate the whole configuration first (geometry, templates) — unsafe configs fail with exit 2 and nothing is changed
- Create target directories if they don't exist
- Migrate existing files/directories from link locations to targets (link → target only)
- Create symlinks from link paths to targets atomically
- Report any per-link failures and exit 5

### 3. Verify Configuration

```bash
boomtube config
```

This validates the config and prints the fully resolved plan (all variables and targets interpolated) without changing anything.

## Configuration

### Configuration File Structure

```yaml
version: 1  # Required, must be the integer 1 (`version: yes` is rejected)

vars:
  # Optional: custom variables for use in target paths
  var_name: "value"
  another_var: "{var_name}/subpath"  # Can reference other vars

links:
  - name: "Human-readable name"        # Optional
    link: "relative/path/in/project"   # Required, must be relative and inside the project
    target: "~/absolute/or/relative"   # Required, supports ~ and variables
    kind: "auto"                       # Optional: auto|file|dir (default: auto)
    migrate: true                      # Optional: enable migration (default: true)
```

### Built-in Variables

- `{project_root}`: Absolute path to the project root directory
- `{project_name}`: Name of the project root directory

`project_root` and `project_name` are built-ins and **cannot be overridden** by user variables; a config that defines them as user vars is rejected.

### Link Specification Fields

#### name (optional)

Human-readable identifier for logging and display purposes.

#### link (required)

Relative path within the project where the symlink will be created. Must not be absolute, must not start with `~`, must not be empty, and must not be `.`, `..`, or contain any `..` component (a link like `../outside` or `a/../../b` would escape the project root and is rejected). It must never resolve to the project root itself.

#### target (required)

Destination path for the symlink. Must be non-empty. Can be:
- Absolute path: `/home/user/data`
- Home-relative path: `~/Documents`
- Relative path: `../shared` (resolved relative to project root)
- Variable-interpolated: `{notes_root}/{project_name}`

The target must not be the project root, and must not contain or be contained by its link (nested link/target trees are rejected).

#### kind (optional)

Explicitly specify symlink type:
- `auto` (default): Detect automatically based on existing paths or filename heuristics
- `file`: Force file symlink
- `dir`: Force directory symlink

**Auto-detection rules:**
1. Use explicit `kind` if specified
2. Check if link path exists (use its type)
3. Check if target path exists (use its type)
4. Heuristic: dot-prefixed names without extensions are directories (e.g., `.notes` → dir)
5. Default to file

A `kind` that contradicts the real file/dir type at the link path (e.g. `kind: file` on a real directory) is a per-link error (exit 5), not a crash.

#### migrate (optional)

Enable safe migration when `true` (default: `true`). When enabled:
- Existing content at the link location is copied to the target (link → target only)
- Copies are size-verified before the source is removed
- Conflicts (both sides populated) are refused unless `--force`

When `migrate: false` and the link path already contains real content, `boomtube apply`
refuses and exits 5 — pass `--force` to replace without migrating. Only a *truly empty*
directory is replaced silently: a directory holding only symlinks, only empty subdirectories,
or only conflict-named files counts as non-empty.

## Usage

### Commands

#### apply

Create or update symlinks based on configuration:

```bash
boomtube apply [OPTIONS]
```

**Options:**
- `--config FILE`: Specify config file (default: `boomtube.yaml`)
- `--verbose`: Enable debug logging
- `--force`, `-f`: Override `migrate: false` / both-populated refusals (moves colliding target
  entries aside as conflict files, then seeds from the link side)

**Examples:**

```bash
# Apply with default config
boomtube apply

# Apply with custom config file
boomtube apply --config custom.yaml

# Apply with verbose output
boomtube apply --verbose

# Force a migration despite existing target content (preserved as conflict files)
boomtube apply --force
```

> Concurrent `boomtube apply` runs against the same project are not supported.

#### config

Display the fully resolved configuration:

```bash
boomtube config [OPTIONS]
```

**Options:**
- `--config FILE`: Specify config file (default: `boomtube.yaml`)

Validates the config and prints the fully resolved plan (all variables and targets interpolated) without changing anything.

### Exit Codes

- `0`: Success
- `2`: Config/validation/var-resolution error (nothing was changed)
- `3`: Permission error
- `4`: I/O error
- `5`: One or more links failed to apply (others may have succeeded)

When several per-link failures occur in one run, the most specific exit code wins:
`3` (permission) > `4` (I/O) > `5` (other).

## Safety guarantees

Boomtube rejects, before touching the filesystem, any config that is a data-loss hazard by construction:

- `link` resolving outside the project root (`../`, symlinked parents, `.`)
- `link` resolving to the project root itself
- empty/`.` target, or a target that renders empty
- target resolving to the project root
- link and target overlapping (one inside the other)

Additional guarantees during `apply`:

- Geometry is re-verified for each link against the live filesystem immediately before mutation
- Every copy is **size-verified** before its source can be deleted
- Every entry in the pre-seed **manifest** of the link tree — files, empty directories, and
  symlinks alike — must have a verified copy in the target before the swap proceeds. (The
  manifest is lossless: symlinks are recorded and recreated verbatim, never followed;
  empty directories are recreated; a user's own `*.conflict-from-project-*` files are real
  data, not artifacts)
- Special files (FIFOs/sockets/devices) anywhere in a migrated tree cause a **refusal**, never
  a silent skip
- The swap is atomic: the old path is moved aside, the symlink installed, then the old tree
  removed — a crash at any point leaves data recoverable (in the target or in a `.bt-staging-*`
  tree that a re-run either reclaims or quarantines as `.bt-orphan-*`, which is never
  auto-deleted)
- `migrate: false` never deletes non-empty real content without an explicit `--force` —
  "non-empty" includes directories holding only symlinks, only empty subdirectories, or only
  conflict-named files
- `remove_path` is never called on the project root or its ancestors
- Duplicate or nested link/target paths across links are rejected at preflight (exit 2)

## Migration Behavior

### Directory Migration

When migrating directories (one-directional, link → target):

1. **Scan** the link tree (lstat-based, lossless): regular files, empty directories and
   symlinks are all recorded; symlinks are never followed
2. A type collision at the same relative path (e.g. file vs dir, file vs symlink) is a
   per-link error **before any copy** — no partial state. A target containing only symlinks
   counts as populated
3. **If both the link and target hold real content**, migration refuses (`MigrateCollisionError`,
   exit 5) unless `--force`, which moves only the *colliding* target entries aside as conflict
   files first; non-colliding target content stays in place (the merged tree is a union)
4. Empty directories are **recreated** in the target, shallowest first
5. Files are copied link → target, **size-verified** per copy
6. **Symlinks are copied verbatim, never followed** — including broken and relative ones (a
   relative symlink stays relative; resolving it would silently rewrite it)
7. **Special files (FIFOs/sockets/devices) anywhere in the tree are refused** (`UnsupportedLinkTypeError`,
   exit 5) before anything is mutated
8. Files that disappear mid-migration are skipped (no crash)
9. Hardlinks are not preserved: hardlinked files in a migrated tree are copied as independent
   files (the link relationship is lost)

### File Migration

When migrating individual files (one-directional, link → target):

1. If only the link exists → copied to the target
2. If both exist → refused unless `--force` (target preserved as a conflict file)
3. Never writes through a symlink on either side

### Conflict Files

When automatic resolution isn't possible (both sides populated with `--force`), Boomtube
preserves the *colliding* target entries as conflict files. Non-colliding target content is
left in place — the migrated tree is a union, and only an entry that shares a path with link
content is moved aside:

**Format:** `{original_name}.conflict-from-project-{sha256-of-content (8 chars)}`

**Example:** `.env.local.conflict-from-project-1a2b3c4d`

Conflict files are excluded from future target scans and named deterministically by content
(a symlink's key is its raw target string, never its referent), so re-running an apply is
idempotent with respect to conflicts. The timestamp is preserved in each conflict file's mtime.

## Development

### Development Environment

This project uses [devenv](https://devenv.sh/) with Nix for reproducible development environments:

```bash
# Enter development shell
devenv shell

# Run tests (use `uv run`, not bare `pytest`: in the devenv shell the nix-store
# interpreter is on PATH, and pytest is only on the uv-managed venv's PATH)
devenv shell -- uv run pytest -q
```

### Manual Setup

Without devenv:

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src tests

# Run formatting
ruff format src tests
```

### Project Structure

```
boomtube/
├── src/boomtube/
│   ├── __init__.py       # Package initialization
│   ├── __main__.py       # Entry point for python -m boomtube
│   ├── apply.py          # Per-link apply pipeline (validate -> seed -> verify -> swap)
│   ├── cli.py            # Typer CLI interface (apply, config)
│   ├── config.py         # Configuration loading and validation
│   ├── fsops.py          # Atomic filesystem primitives + crash-residue reclamation
│   ├── hashing.py        # Content hashing utilities
│   ├── manifest.py       # Lossless tree scanner (files, empty dirs, symlinks) + verifier
│   ├── migrate.py        # One-directional seed (link -> target) + collision handling
│   ├── models.py         # Pydantic data models (static, context-free validation)
│   ├── planning.py       # Preflight plan: render targets, geometry validation
│   ├── resolve.py        # Variable resolution
│   └── util.py           # Utility functions (conflict naming, unique paths)
├── tests/                # Test suite
├── pyproject.toml        # Project metadata and dependencies
└── boomtube.yaml         # Configuration file (user-created)
```

## Testing

### Run All Tests

```bash
uv run pytest
```

### Run with Coverage

```bash
uv run pytest --cov=boomtube --cov-report=term-missing
```

### Run Specific Test Files

```bash
uv run pytest tests/test_migrate_dirs.py
uv run pytest tests/test_config.py
```

### Test Coverage

The test suite covers:
- Configuration loading and validation
- Variable resolution with builtin and custom variables
- Geometry validation (containment, overlap, root safety)
- Kind auto-detection and consistency
- One-directional file and directory seeding
- Conflict detection, naming, and idempotency
- Symlink application, verification, and atomic swap crash windows

## Architecture Notes

### Design Principles

- **Pydantic Models**: All configuration and data structures use Pydantic for validation
- **Validate → Plan → Verify → Swap**: nothing is mutated until the whole plan is validated; every copy is verified before deletion; replacement is atomic
- **Explicit over Implicit**: clear, actionable error messages; refusals instead of silent merges
- **Safety First**: Never delete data without a verified copy and an explicit, safe operation

### Key Algorithms

**Variable Resolution:**
- Dependency-ordered resolution with cycle detection (DFS memoization)
- `project_root`/`project_name` are built-in and cannot be overridden by user vars
- All templates are rendered during preflight, before any filesystem mutation

**Migration Logic:**
- Lossless manifest scan (lstat): files, empty directories, and symlinks are all recorded
- One-directional seed (link → target); both-populated is refused unless `--force`
- Type collisions across all kinds checked before any copy
- Size-verified copies; vanished files skipped
- Symlinks recreated verbatim (relative stays relative); special files refused
- Deterministic conflict files named by content hash, excluded from future target scans
- Crash residue (`.bt-staging-*`/`.bt-tmp-*`) is only deleted when verified against the target;
  unverifiable residue is quarantined as `.bt-orphan-*` and never auto-deleted

**Symlink Management:**
- Geometry validated at preflight and re-verified per link at apply time
- Atomic symlink creation/replacement (temp symlink + `os.replace`)
- Crash-safe swap: old tree moved aside, symlink installed, old tree deleted

## License

MIT

## Contributing

Contributions are welcome. Please ensure:
- All tests pass: `uv run pytest`
- Code is formatted: `ruff format`
- Linting passes: `ruff check`
- Line length stays under 120 characters
- New features include tests

## Version History

### 0.3.0 (Current)

Manifest-safety release (002): every safety mechanism is now defined in terms of a lossless
manifest, closing the gap where symlinks, special files, empty directories, and conflict-named
files inside a migrated directory were silently deleted:

- **Lossless tree manifests**: symlinks are recreated verbatim (never followed, relative stays
  relative); empty directories are recreated; a user's own `*.conflict-from-project-*` files are
  treated as real data
- **Special files refused**: a FIFO/socket/device anywhere in a migrated tree is a typed refusal
  before anything is mutated, never silent loss
- **Verified crash-residue reclamation**: `.bt-staging-*` trees are only deleted when their
  contents are verified in the target; anything unverifiable is quarantined as `.bt-orphan-*`
  and never auto-deleted; reclaim globs are metachar-escaped
- **`migrate: false` now honors the README guarantee**: a directory holding only symlinks, only
  empty subdirs, or only conflict-named files counts as non-empty and requires `--force`
- **Cross-link preflight**: duplicate or nested link/target paths are rejected at preflight (exit 2)
- **Symlink repointing** (editing `target:`) creates the new target instead of leaving a dangling
  link; dangling file symlinks are reported as a warning, exit stays 0
- **Reachable exit codes**: real `PermissionError` during apply → 3, plain `OSError` → 4
  (precedence 3 > 4 > 5); an explicit `--project-root` wins over the config's parent
- **`extra="forbid"`**: a typo like `migrat: false` is rejected instead of silently ignored
- **Hardenings**: NUL-byte validation (including via `{var}` rendering), basename-based dot
  heuristic, `lexists`-based unique paths, block-wise identical-file comparison, dead code removal

### 0.2.0

Major safety and usability release:
- **Validate → plan → verify → swap pipeline**: geometry and templates are validated before any filesystem mutation; unsafe configs fail with exit 2 and zero changes
- **One-directional migration** (link → target only); both-populated content is refused unless `--force` (target preserved as deterministic conflict files)
- **Size-verified copies and atomic swap**: deletion only after verified duplication; crash-safe replacement
- **Typed per-link errors** with continue-on-error and exit code 5
- **`boomtube config` command**: prints the fully resolved plan without changing anything
- **Documented exit codes** 0/2/3/4/5
- typer floor raised to `>=0.15.4` (validated against 0.15.4/0.16.0/0.27.1)

### 0.1.0

Initial MVP release with:
- YAML configuration
- Safe file and directory migration
- Variable interpolation
- CLI interface
- Comprehensive test coverage
