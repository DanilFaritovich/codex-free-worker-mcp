from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    opencode_bin: str = "opencode"
    model: str = "openrouter/cohere/north-mini-code:free"
    timeout_seconds: int = 900
    max_result_chars: int = 8_000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            opencode_bin=os.getenv("FREE_WORKER_OPENCODE_BIN", "opencode"),
            model=os.getenv(
                "FREE_WORKER_MODEL",
                "openrouter/cohere/north-mini-code:free",
            ),
            timeout_seconds=int(os.getenv("FREE_WORKER_TIMEOUT_SECONDS", "900")),
            max_result_chars=int(os.getenv("FREE_WORKER_MAX_RESULT_CHARS", "8000")),
        )
