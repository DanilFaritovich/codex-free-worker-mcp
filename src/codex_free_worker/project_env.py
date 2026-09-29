from __future__ import annotations

import os
import shutil
from pathlib import Path


def build_project_env(cwd: Path) -> dict[str, str]:
    """Expose target-repository venv executables without changing the MCP process."""
    env = os.environ.copy()
    venvs = (cwd / ".venv", cwd / "backend" / ".venv")
    available = [venv for venv in venvs if (venv / "bin").is_dir()]
    if not available:
        return env

    prefix = os.pathsep.join(str(venv / "bin") for venv in available)
    previous_path = env.get("PATH", "")
    env["PATH"] = f"{prefix}{os.pathsep}{previous_path}" if previous_path else prefix
    env["VIRTUAL_ENV"] = str(available[0])
    return env


def resolve_backend_binary(binary: str) -> str:
    """Find the worker executable on the original PATH, before prepending project bins."""
    if "/" in binary:
        return binary
    return shutil.which(binary) or binary
