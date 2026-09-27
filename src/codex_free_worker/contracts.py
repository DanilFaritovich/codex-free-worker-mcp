from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkerMode(StrEnum):
    INSPECT = "inspect"
    FIX = "fix"


class WorkerStatus(StrEnum):
    PASSED = "passed"
    FIXED = "fixed"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    cwd: Path
    mode: WorkerMode

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task must not be empty")
        return value


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorkerStatus
    summary: str = Field(min_length=1)
    changed_files: list[str] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)
    relevant_locations: list[str] = Field(default_factory=list)
    needs_main_model_decision: bool = False
    decision_required: str | None = None
