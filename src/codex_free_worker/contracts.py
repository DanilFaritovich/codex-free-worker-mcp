from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkerBackend(StrEnum):
    OPENCODE = "opencode"
    CODEX = "codex"


class WorkerMode(StrEnum):
    INSPECT = "inspect"
    FIX = "fix"


class SandboxMode(StrEnum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"


class WorkerStatus(StrEnum):
    PASSED = "passed"
    FIXED = "fixed"
    FAILED = "failed"
    BLOCKED = "blocked"


class BlockedOperationKind(StrEnum):
    FILE_READ = "file-read"
    FILE_WRITE = "file-write"
    COMMAND = "command"
    NETWORK = "network"
    OTHER = "other"


class BlockedOperation(BaseModel):
    """Information for the parent agent to evaluate; never executable authority."""

    model_config = ConfigDict(extra="forbid")

    kind: BlockedOperationKind
    target: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


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
    blocked_operation: BlockedOperation | None = None

    @model_validator(mode="after")
    def validate_permission_handoff(self) -> WorkerResult:
        if self.blocked_operation is not None:
            if self.status is not WorkerStatus.BLOCKED:
                raise ValueError("blocked_operation requires status=blocked")
            if not self.needs_main_model_decision or not (
                self.decision_required and self.decision_required.strip()
            ):
                raise ValueError("blocked_operation requires a parent decision")
        return self


class CodexCheck(BaseModel):
    """A named check with a fixed shape suitable for strict structured output."""

    model_config = ConfigDict(extra="forbid")

    name: str
    result: str


class CodexWorkerResult(BaseModel):
    """Codex-facing envelope; the public MCP contract keeps dict-shaped checks."""

    model_config = ConfigDict(extra="forbid")

    status: WorkerStatus
    summary: str = Field(min_length=1)
    changed_files: list[str]
    checks: list[CodexCheck]
    relevant_locations: list[str]
    needs_main_model_decision: bool
    decision_required: str | None
    blocked_operation: BlockedOperation | None

    def to_worker_result(self) -> WorkerResult:
        return WorkerResult(
            status=self.status,
            summary=self.summary,
            changed_files=self.changed_files,
            checks={check.name: check.result for check in self.checks},
            relevant_locations=self.relevant_locations,
            needs_main_model_decision=self.needs_main_model_decision,
            decision_required=self.decision_required,
            blocked_operation=self.blocked_operation,
        )


def worker_result_json_schema() -> dict[str, object]:
    """Use fixed-shape check items: strict output disallows arbitrary map keys."""
    return CodexWorkerResult.model_json_schema()
