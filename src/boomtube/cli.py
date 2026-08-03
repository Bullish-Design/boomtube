from __future__ import annotations

import logging
from pathlib import Path

import typer

from .apply import apply_plan
from .config import ConfigError, load_config
from .planning import PlanError, build_plan
from .resolve import VarResolutionError, build_context

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Boomtube: project-local symlink manager (MVP)"
)


@app.callback()
def _main() -> None:
    """Boomtube: project-local symlink manager.

    Use `boomtube apply` to create/update symlinks from boomtube.yaml.
    """


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@app.command(name="apply")
def apply(
    project_root: Path = typer.Option(
        Path.cwd(), "--project-root", help="Project root directory (defaults to cwd)"
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to boomtube.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Override migrate:false / both-populated refusals by replacing target content"
    ),
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
        planned = build_plan(project_root_resolved, cfg, ctx)
        result = apply_plan(project_root_resolved, planned, force=force)
        if result.failed:
            for path, exc in result.failed:
                logging.error("failed to apply link at %s: %s", path, exc)
            logging.error(
                "applied %d/%d links", len(result.applied), len(result.applied) + len(result.failed)
            )
            raise typer.Exit(code=5)
    except (ConfigError, VarResolutionError, PlanError) as e:
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
