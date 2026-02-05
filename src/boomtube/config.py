from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import BoomtubeConfig


class ConfigError(RuntimeError):
    pass


def load_config(config_path: Path) -> BoomtubeConfig:
    """Load and validate a Boomtube config from YAML."""
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigError(f"Config not found: {config_path}") from e
    except OSError as e:
        raise ConfigError(f"Unable to read config: {config_path}: {e}") from e

    try:
        data = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {config_path}: {e}") from e

    try:
        return BoomtubeConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation error in {config_path}: {e}") from e
    except ValueError as e:
        raise ConfigError(f"Config validation error in {config_path}: {e}") from e
