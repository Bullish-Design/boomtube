from __future__ import annotations

import logging
from pathlib import Path

import typer

from .apply import apply_all
from .config import ConfigError, load_config
from .resolve import VarResolutionError, build_context

app = typer.Typer(add_completion=False, help="Boomtube: project-local symlink manager (MVP)")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@app.command()
def apply(
    project_root: Path = typer.Option(
        Path.cwd(), "--project-root", help="Project root directory (defaults to cwd)"
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to boomtube.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Apply symlink config (create/replace symlinks, optionally migrate)."""
    _configure_logging(verbose)

    try:
        if config is not None:
            config_path = config.expanduser().resolve(strict=False)
            project_root_resolved = config_path.parent
        else:
            project_root_resolved = project_root.expanduser().resolve(strict=False)
            config_path = project_root_resolved / "boomtube.yaml"

        cfg = load_config(config_path)
        ctx = build_context(project_root_resolved, cfg.vars)
        apply_all(project_root_resolved, cfg.links, ctx)
    except (ConfigError, VarResolutionError) as e:
        logging.error(str(e))
        raise typer.Exit(code=2)
    except PermissionError as e:
        logging.error(f"Permission error: {e}")
        raise typer.Exit(code=3)
    except OSError as e:
        logging.error(f"OS error: {e}")
        raise typer.Exit(code=4)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
