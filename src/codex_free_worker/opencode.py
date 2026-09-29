"""Backward-compatible OpenCode adapter exports."""

from codex_free_worker.adapters.opencode import (
    OpenCodeAdapter,
    _parse_result,
    _parse_result_lines,
)

__all__ = ["OpenCodeAdapter", "_parse_result", "_parse_result_lines"]
