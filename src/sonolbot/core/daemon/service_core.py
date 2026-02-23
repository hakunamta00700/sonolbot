from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from sonolbot.core.daemon.runtime_shared import *


class DaemonServiceCoreEnvPolicy:
    def build_default_env(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(base_env or os.environ)
        env.setdefault("LANG", "C.UTF-8")
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "UTF-8")
        env["SONOLBOT_GUI_SESSION"] = "1" if self.has_gui_session(env) else "0"
        return env

    def has_gui_session(self, env: dict[str, str]) -> bool:
        if os.name == "nt":
            return True
        return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


class DaemonServiceCoreRuntime:
    def __init__(self, service: Any, env_policy: DaemonServiceCoreEnvPolicy | None = None) -> None:
        self.service = service
        self.env_policy = env_policy or DaemonServiceCoreEnvPolicy()
        self.python_bin = self._detect_python_bin()
        self.codex_run_meta: Optional[dict[str, object]] = None
        self.codex_cli_version = ""
        self.stop_requested = False
        self.env = self._build_default_env()

    def _build_default_env(self) -> dict[str, str]:
        return self.env_policy.build_default_env()

    def set_env(self, env: dict[str, str]) -> None:
        self.env = self._sanitize_env(dict(env))

    def _sanitize_env(self, env: dict[str, str]) -> dict[str, str]:
        normalized = dict(env)
        normalized["SONOLBOT_GUI_SESSION"] = (
            "1" if self._has_gui_session(normalized) else "0"
        )
        return normalized

    def _detect_python_bin(self) -> str:
        root = getattr(self.service, "root", None)
        if isinstance(root, Path):
            candidate_paths = self._candidate_venv_python_paths(root)

            for venv_py in candidate_paths:
                if venv_py.exists():
                    return str(venv_py)
        return sys.executable

    def _candidate_venv_python_paths(self, root: Path) -> list[Path]:
        candidates: list[Path] = [root / ".venv" / "bin" / "python", root / ".venv" / "bin" / "python3"]
        if os.name == "nt":
            candidates.insert(0, root / ".venv" / "Scripts" / "python.exe")
            candidates.insert(1, root / ".venv" / "Scripts" / "python3.exe")
        return candidates

    def _has_gui_session(self, env: dict[str, str] | None = None) -> bool:
        target = dict(self.env) if env is None else env
        return self.env_policy.has_gui_session(target)


class DaemonServiceCoreMixin:
    def _init_core_runtime(
        self,
        core_runtime: DaemonServiceCoreRuntime | None = None,
        *,
        env_policy: DaemonServiceCoreEnvPolicy | None = None,
    ) -> None:
        if core_runtime is None:
            core_runtime = DaemonServiceCoreRuntime(self, env_policy=env_policy)
        self._core_runtime_component = core_runtime

    def _get_core_runtime(self) -> DaemonServiceCoreRuntime | None:
        runtime = getattr(self, "_core_runtime_component", None)
        if isinstance(runtime, DaemonServiceCoreRuntime):
            return runtime
        return None

    def _has_gui_session(self) -> bool:
        runtime = self._get_core_runtime()
        if runtime is None:
            return False
        return runtime._has_gui_session(runtime.env)

    @property
    def python_bin(self) -> str:
        runtime = self._get_core_runtime()
        if runtime is None:
            return sys.executable
        return runtime.python_bin

    @python_bin.setter
    def python_bin(self, value: str) -> None:
        runtime = self._get_core_runtime()
        if runtime is None:
            return
        runtime.python_bin = str(value)

    @property
    def codex_run_meta(self) -> Optional[dict[str, object]]:
        runtime = self._get_core_runtime()
        if runtime is None:
            return None
        return runtime.codex_run_meta

    @codex_run_meta.setter
    def codex_run_meta(self, value: Optional[dict[str, object]]) -> None:
        runtime = self._get_core_runtime()
        if runtime is None:
            return
        runtime.codex_run_meta = value

    @property
    def codex_cli_version(self) -> str:
        runtime = self._get_core_runtime()
        if runtime is None:
            return ""
        return runtime.codex_cli_version

    @codex_cli_version.setter
    def codex_cli_version(self, value: str) -> None:
        runtime = self._get_core_runtime()
        if runtime is None:
            return
        runtime.codex_cli_version = value

    @property
    def stop_requested(self) -> bool:
        runtime = self._get_core_runtime()
        if runtime is None:
            return False
        return bool(runtime.stop_requested)

    @stop_requested.setter
    def stop_requested(self, value: bool) -> None:
        runtime = self._get_core_runtime()
        if runtime is None:
            return
        runtime.stop_requested = bool(value)

    @property
    def env(self) -> dict[str, str]:
        runtime = self._get_core_runtime()
        if runtime is None:
            return os.environ.copy()
        return runtime.env

    @env.setter
    def env(self, value: dict[str, str]) -> None:
        runtime = self._get_core_runtime()
        if runtime is None:
            return
        runtime.set_env(value)
