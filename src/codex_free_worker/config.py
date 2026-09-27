from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_allowed_roots(raw: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    for item in raw.split(os.pathsep):
        value = item.strip()
        if not value:
            continue

        root = Path(value).expanduser()
        if not root.is_absolute():
            raise ValueError("FREE_WORKER_ALLOWED_ROOTS entries must be absolute paths")
        roots.append(root.resolve())

    return tuple(roots)


@dataclass(frozen=True, slots=True)
class Settings:
    opencode_bin: str = "opencode"
    model: str = "openrouter/cohere/north-mini-code:free"
    timeout_seconds: int = 840
    max_result_chars: int = 8_000
    allowed_roots: tuple[Path, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            opencode_bin=os.getenv("FREE_WORKER_OPENCODE_BIN", "opencode"),
            model=os.getenv(
                "FREE_WORKER_MODEL",
                "openrouter/cohere/north-mini-code:free",
            ),
            timeout_seconds=int(os.getenv("FREE_WORKER_TIMEOUT_SECONDS", "840")),
            max_result_chars=int(os.getenv("FREE_WORKER_MAX_RESULT_CHARS", "8000")),
            allowed_roots=_parse_allowed_roots(os.getenv("FREE_WORKER_ALLOWED_ROOTS", "")),
        )
