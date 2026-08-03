from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Kind = Literal["auto", "file", "dir"]


class LinkSpec(BaseModel):
    """One symlink specification."""

    name: str | None = None
    link: str
    target: str
    kind: Kind = "auto"
    migrate: bool = True

    @field_validator("link")
    @classmethod
    def link_must_be_relative(cls, v: str) -> str:
        # Avoid empty path.
        if v.strip() == "":
            raise ValueError("link must be non-empty")
        p = Path(v)
        if p.is_absolute():
            raise ValueError("link must be a relative path")
        # Disallow home expansion in link path; it must be within project root.
        if v.startswith("~"):
            raise ValueError("link must be relative to project root (must not start with '~')")
        # Reject '.', '..' and any path containing a '..' component: a link like
        # `..` (or `a/../../b`) would resolve to the project root itself or
        # escape it entirely, and the apply flow may delete the resolved path.
        stripped = v.strip()
        if stripped in {".", ".."}:
            raise ValueError(f"link must not be the project root itself ('{stripped}')")
        components = [c for c in re.split(r"[/\\]+", stripped) if c not in ("", ".")]
        if ".." in components:
            raise ValueError("link must not contain '..' components (it must stay inside the project root)")
        return v

    @field_validator("target")
    @classmethod
    def target_must_be_non_empty(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("target must be non-empty")
        return v

    @field_validator("kind")
    @classmethod
    def kind_allowed(cls, v: str) -> str:
        if v not in {"auto", "file", "dir"}:
            raise ValueError("kind must be one of: auto, file, dir")
        return v


class BoomtubeConfig(BaseModel):
    version: int
    vars: dict[str, str] = Field(default_factory=dict)
    links: list[LinkSpec]

    @field_validator("version", mode="before")
    @classmethod
    def version_must_not_be_bool(cls, v):
        # Pydantic coerces bool -> int before `validate_config` runs, so a YAML
        # `version: yes` (PyYAML 1.1 bool) would otherwise be silently accepted
        # as 1. Reject the raw boolean input explicitly.
        if isinstance(v, bool):
            raise ValueError("version must be an integer, not a boolean (did you write 'version: yes'?)")
        return v

    @model_validator(mode="after")
    def validate_config(self) -> BoomtubeConfig:
        if self.version != 1:
            raise ValueError("config version must be 1")
        if not self.links:
            raise ValueError("links must be non-empty")
        for key in ("project_root", "project_name"):
            if key in self.vars:
                raise ValueError(f"vars cannot override built-in variable '{key}'")
        return self
