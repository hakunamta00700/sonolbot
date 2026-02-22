"""Run daemon_service in foreground (replacement for mybot_autoexecutor.sh)."""

from __future__ import annotations

import os
import subprocess
import sys

from sonolbot.runtime import project_root, venv_python


def _pick_python() -> str:
    venv = venv_python()
    if venv.exists():
        return str(venv)
    if os.name == "nt":
        if os.path.exists(r"C:\\Python39\\python.exe"):
            return r"C:\\Python39\\python.exe"
    for name in ("python3", "python"):
        if os.system(f'command -v {name} >/dev/null 2>&1') == 0:
            return name
    return "python"


def run_daemon_service() -> int:
    python_bin = _pick_python()
    proc = subprocess.run(
        [python_bin, "-m", "sonolbot.core.daemon_service"],
        cwd=str(project_root()),
    )
    return int(proc.returncode)


def main() -> int:
    return run_daemon_service()


if __name__ == "__main__":
    raise SystemExit(main())
