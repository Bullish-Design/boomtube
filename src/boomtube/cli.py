from __future__ import annotations

import logging
from pathlib import Path

import typer
import yaml

from .apply import apply_plan
from .config import ConfigError, load_config
from .planning import PlanError, build_plan
from .resolve import VarResolutionError, build_context

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Boomtube: project-local symlink manager"
)


@app.callback()
def _main() -> None:
    """Boomtube: project-local symlink manager.

    Use `boomtube apply` to create/update symlinks from boomtube.yaml.
    """


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _resolve_project_and_config(project_root: Path, config: Path | None) -> tuple[Path, Path]:
    """Resolve the project root and config path (config's parent wins as the root)."""
    if config is not None:
        config_path = config.expanduser().resolve(strict=False)
        return config_path.parent, config_path
    project_root_resolved = project_root.expanduser().resolve(strict=False)
    return project_root_resolved, project_root_resolved / "boomtube.yaml"


def _load_plan(project_root_resolved: Path, config_path: Path):
    """Shared load -> resolve -> plan pipeline (raises the typed preflight errors)."""
    cfg = load_config(config_path)
    ctx = build_context(project_root_resolved, cfg.vars)
    planned = build_plan(project_root_resolved, cfg, ctx)
    return cfg, ctx, planned


@app.command(name="apply")
def apply(
    project_root: Path = typer.Option(  # noqa: B008
        Path.cwd(), "--project-root", help="Project root directory (defaults to cwd)"  # noqa: B008
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to boomtube.yaml"),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),  # noqa: B008
    force: bool = typer.Option(  # noqa: B008
        False, "--force", "-f", help="Override migrate:false / both-populated refusals by replacing target content"
    ),
) -> None:
    """Apply symlink config (create/replace symlinks, optionally migrate)."""
    _configure_logging(verbose)

    try:
        project_root_resolved, config_path = _resolve_project_and_config(project_root, config)
        _, _, planned = _load_plan(project_root_resolved, config_path)
        result = apply_plan(project_root_resolved, planned, force=force)
        if result.failed:
            by_path = {pl.link_path: pl.spec for pl in planned}
            for path, exc in result.failed:
                spec = by_path.get(path)
                display = (spec.name or spec.link) if spec else str(path)
                logging.error("failed to apply link '%s': %s", display, exc)
            logging.error(
                "applied %d/%d links", len(result.applied), len(result.applied) + len(result.failed)
            )
            raise typer.Exit(code=5)
    except (ConfigError, VarResolutionError, PlanError) as e:
        logging.error(str(e))
        raise typer.Exit(code=2) from None
    except PermissionError as e:
        logging.error(f"Permission error: {e}")
        raise typer.Exit(code=3) from None
    except OSError as e:
        logging.error(f"OS error: {e}")
        raise typer.Exit(code=4) from None


@app.command(name="config")
def config(
    project_root: Path = typer.Option(  # noqa: B008
        Path.cwd(), "--project-root", help="Project root directory (defaults to cwd)"  # noqa: B008
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to boomtube.yaml"),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),  # noqa: B008
) -> None:
    """Validate the config and print the fully resolved plan without changing anything."""
    _configure_logging(verbose)

    try:
        project_root_resolved, config_path = _resolve_project_and_config(project_root, config)
        cfg, ctx, planned = _load_plan(project_root_resolved, config_path)
    except (ConfigError, VarResolutionError, PlanError) as e:
        logging.error(str(e))
        raise typer.Exit(code=2) from None
    except PermissionError as e:
        logging.error(f"Permission error: {e}")
        raise typer.Exit(code=3) from None
    except OSError as e:
        logging.error(f"OS error: {e}")
        raise typer.Exit(code=4) from None

    resolved = {
        "version": cfg.version,
        "vars": ctx,
        "links": [
            {
                "name": pl.spec.name,
                "link": pl.spec.link,
                "target": str(pl.target_path),
                "kind": pl.spec.kind,
                "migrate": pl.migrate,
            }
            for pl in planned
        ],
    }
    typer.echo(yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True).rstrip())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
