from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class WorkerMode(StrEnum):
    INSPECT = "inspect"
    FIX = "fix"


class WorkerStatus(StrEnum):
    PASSED = "passed"
    FIXED = "fixed"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkerResult(BaseModel):
    status: WorkerStatus
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)
    relevant_locations: list[str] = Field(default_factory=list)
    needs_main_model_decision: bool = False
    decision_required: str | None = None
