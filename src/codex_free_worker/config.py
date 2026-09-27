from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    opencode_bin: str = Field(
        default="opencode",
        validation_alias="FREE_WORKER_OPENCODE_BIN",
    )
    opencode_model: str = Field(
        default="openrouter/cohere/north-mini-code:free",
        validation_alias=AliasChoices("FREE_WORKER_OPENCODE_MODEL", "FREE_WORKER_MODEL"),
    )
    timeout_seconds: int = Field(
        default=840,
        ge=1,
        validation_alias="FREE_WORKER_TIMEOUT_SECONDS",
    )
    max_result_chars: int = Field(
        default=8_000,
        ge=1,
        validation_alias="FREE_WORKER_MAX_RESULT_CHARS",
    )
    allowed_roots: Annotated[tuple[Path, ...], NoDecode] = Field(
        default=(),
        validation_alias="FREE_WORKER_ALLOWED_ROOTS",
    )

    @field_validator("allowed_roots", mode="before")
    @classmethod
    def parse_allowed_roots(cls, value: object) -> object:
        if value in (None, ""):
            return ()
        if not isinstance(value, str):
            return value

        roots: list[Path] = []
        for item in value.split(os.pathsep):
            item = item.strip()
            if not item:
                continue

            root = Path(item).expanduser()
            if not root.is_absolute():
                raise ValueError("FREE_WORKER_ALLOWED_ROOTS entries must be absolute paths")
            roots.append(root.resolve())

        return tuple(roots)

    @classmethod
    def from_env(cls) -> Settings:
        return cls()
