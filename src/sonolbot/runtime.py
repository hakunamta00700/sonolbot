"""Shared runtime helpers for CLI and legacy-script migration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    """Return repository root where this file is located."""
    return Path(__file__).resolve().parents[3]


def env_path(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _has_content(path: Path) -> bool:
    try:
        return any(path.iterdir())
    except OSError:
        return False


def agent_home() -> Path:
    configured = os.getenv("SONOLBOT_AGENT_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    runtime_home = project_root() / "agent_runtime"
    return runtime_home


def agent_runtime() -> Path:
    return agent_home()


def codex_root() -> Path:
    preferred = agent_runtime() / ".codex"
    if preferred.exists() and _has_content(preferred):
        return preferred
    return project_root() / ".codex"


def skills_root() -> Path:
    return codex_root() / "skills"


def logs_root() -> Path:
    return Path(env_path("LOGS_DIR", str(project_root() / "logs"))).expanduser().resolve()


def tasks_root() -> Path:
    return Path(env_path("TASKS_DIR", str(project_root() / "tasks"))).expanduser().resolve()


def venv_python() -> Path:
    if os.name == "nt":
        return project_root() / ".venv" / "Scripts" / "python.exe"
    return project_root() / ".venv" / "bin" / "python"


def project_file(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def agent_config(name: str) -> Path:
    return agent_home() / name


@dataclass
class AgentRuntimePaths:
    root: Path
    codex: Path
    skills: Path


def resolve_paths() -> AgentRuntimePaths:
    base = project_root()
    runtime = agent_runtime()
    if not runtime.exists():
        runtime = base
    return AgentRuntimePaths(
        root=runtime,
        codex=codex_root(),
        skills=codex_root() / "skills",
    )
