from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


Kind = Literal["auto", "file", "dir"]


class LinkSpec(BaseModel):
    """One symlink specification."""

    name: Optional[str] = None
    link: str
    target: str
    kind: Kind = "auto"
    migrate: bool = True

    @field_validator("link")
    @classmethod
    def link_must_be_relative(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute():
            raise ValueError("link must be a relative path")
        # Disallow home expansion in link path; it must be within project root.
        if v.startswith("~"):
            raise ValueError("link must be relative to project root (must not start with '~')")
        # Avoid empty path.
        if v.strip() == "":
            raise ValueError("link must be non-empty")
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

    @model_validator(mode="after")
    def validate_config(self) -> "BoomtubeConfig":
        if self.version != 1:
            raise ValueError("config version must be 1")
        if not self.links:
            raise ValueError("links must be non-empty")
        return self
