# README.md

# Boomtube

Project-local symlink manager with safe migration

## Overview

Boomtube manages symlinks within your project directories using a declarative YAML configuration. It safely migrates existing files and directories when creating new symlinks, ensuring no data loss through intelligent conflict resolution.

## Features

### Core Capabilities

- **Declarative Configuration**: Define all project symlinks in a single `boomtube.yaml` file
- **Safe Migration**: Automatically migrate existing files/directories before creating symlinks
- **Conflict Resolution**: Preserves both versions when files differ and have identical modification times
- **Variable Interpolation**: Use variables in target paths with built-in and custom variables
- **Automatic Kind Detection**: Intelligently detects whether to create file or directory symlinks
- **Idempotent Operations**: Safe to run multiple times without side effects

### Migration Strategy

Boomtube uses a content-aware migration strategy:

- **Modification Time Priority**: Newer files automatically overwrite older ones
- **Content Hashing**: Uses SHA-256 to detect identical content regardless of timestamps
- **Conflict Preservation**: Creates `.conflict-from-project-*` files when automatic resolution isn't possible
- **Bidirectional Sync**: Merges content from both source and target locations

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
- Create target directories if they don't exist
- Migrate existing files/directories from link locations to targets
- Create symlinks from link paths to targets
- Report any conflicts that require manual resolution

### 3. Verify Configuration

```bash
boomtube config
```

This displays the resolved configuration with all variables interpolated.

## Configuration

### Configuration File Structure

```yaml
version: 1  # Required, must be 1

vars:
  # Optional: custom variables for use in target paths
  var_name: "value"
  another_var: "{var_name}/subpath"  # Can reference other vars

links:
  - name: "Human-readable name"        # Optional
    link: "relative/path/in/project"   # Required, must be relative
    target: "~/absolute/or/relative"   # Required, supports ~ and variables
    kind: "auto"                       # Optional: auto|file|dir (default: auto)
    migrate: true                      # Optional: enable migration (default: false)
```

### Built-in Variables

- `{project_root}`: Absolute path to the project root directory
- `{project_name}`: Name of the project root directory

### Link Specification Fields

#### name (optional)

Human-readable identifier for logging and display purposes.

#### link (required)

Relative path within the project where the symlink will be created. Must not be absolute.

#### target (required)

Destination path for the symlink. Can be:
- Absolute path: `/home/user/data`
- Home-relative path: `~/Documents`
- Relative path: `../shared` (resolved relative to project root)
- Variable-interpolated: `{notes_root}/{project_name}`

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

#### migrate (optional)

Enable safe migration when `true` (default: `false`). When enabled:
- Existing content at link location is merged with target location
- Newer files overwrite older files
- Identical files are detected via content hashing
- Conflicts are preserved as separate files

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

**Examples:**

```bash
# Apply with default config
boomtube apply

# Apply with custom config file
boomtube apply --config custom.yaml

# Apply with verbose output
boomtube apply --verbose
```

#### config

Display resolved configuration:

```bash
boomtube config [OPTIONS]
```

**Options:**
- `--config FILE`: Specify config file (default: `boomtube.yaml`)

Shows the configuration with all variables resolved and validated.

### Exit Codes

- `0`: Success
- `1`: Configuration error, resolution error, or other failure

## Migration Behavior

### Directory Migration

When migrating directories:

1. **Recursively traverse** both source and target directories
2. **Skip symlinks** within directories (not followed)
3. **For each file path:**
   - If only in source → copy to target
   - If only in target → copy to source
   - If in both with identical content → skip
   - If in both with different mtimes → copy newer to location of older
   - If in both with same mtime but different content → create conflict file

### File Migration

When migrating individual files:

1. **If only source exists** → copy to target location
2. **If only target exists** → copy to source location
3. **If both exist:**
   - Compare content hashes
   - If identical → skip
   - If different mtimes → copy newer file to other location
   - If same mtime → create conflict file at target location

### Conflict Files

When automatic resolution isn't possible (same mtime, different content), Boomtube creates a conflict file:

**Format:** `{original_name}.conflict-from-project-{timestamp}`

**Example:** `.env.local.conflict-from-project-20250207-160305`

The original file remains unchanged at the target location. The conflicting version from the project is saved with the conflict suffix.

## Development

### Development Environment

This project uses [devenv](https://devenv.sh/) with Nix for reproducible development environments:

```bash
# Enter development shell
devenv shell

# Run tests in devenv
devenv test
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
│   ├── apply.py          # Symlink application logic
│   ├── cli.py            # Typer CLI interface
│   ├── config.py         # Configuration loading and validation
│   ├── fsops.py          # File system operations
│   ├── hashing.py        # Content hashing utilities
│   ├── migrate.py        # File/directory migration logic
│   ├── models.py         # Pydantic data models
│   ├── resolve.py        # Variable resolution
│   └── util.py           # Utility functions
├── tests/                # Test suite
├── pyproject.toml        # Project metadata and dependencies
└── boomtube.yaml         # Configuration file (user-created)
```

## Testing

### Run All Tests

```bash
pytest
```

### Run with Coverage

```bash
pytest --cov=boomtube --cov-report=term-missing
```

### Run Specific Test Files

```bash
pytest tests/test_migrate_dirs.py
pytest tests/test_config.py
```

### Test Coverage

The test suite covers:
- Configuration loading and validation
- Variable resolution with builtin and custom variables
- Kind auto-detection
- File and directory migration
- Conflict resolution
- Symlink application and replacement

## Architecture Notes

### Design Principles

- **Pydantic Models**: All configuration and data structures use Pydantic for validation
- **Functional Core**: Pure functions for migration logic and resolution
- **Explicit over Implicit**: Clear, verbose error messages
- **Safety First**: Never delete data without migration or explicit user action

### Key Algorithms

**Variable Resolution:**
- Topological sort to resolve dependencies between variables
- Cycle detection to prevent infinite loops
- Built-in variables injected before user variables

**Migration Logic:**
- Content-based comparison using SHA-256 hashing
- mtime-based freshness determination
- Conflict files preserve all versions when automatic merge fails

**Symlink Management:**
- Normalization to absolute paths for comparison
- Safe removal and recreation of stale symlinks
- Parent directory creation as needed

## License

MIT

## Contributing

Contributions are welcome. Please ensure:
- All tests pass: `pytest`
- Code is formatted: `ruff format`
- Linting passes: `ruff check`
- Line length stays under 120 characters
- New features include tests

## Version History

### 0.1.0 (Current)

Initial MVP release with:
- YAML configuration
- Safe file and directory migration
- Variable interpolation
- CLI interface
- Comprehensive test coverage
