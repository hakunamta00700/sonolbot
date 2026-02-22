"""Run daemon_control_panel in foreground / build PyInstaller exe."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from sonolbot.runtime import logs_root, project_root, venv_python


def _pick_python() -> str:
    venv = venv_python()
    if venv.exists():
        return str(venv)

    if shutil.which("py"):
        return "py"
    if shutil.which("python"):
        return "python"
    return "python"


def _check_tkinter(python_bin: str) -> bool:
    try:
        subprocess.run(
            [python_bin, "-c", "import tkinter"], check=True, capture_output=True, text=True
        )
        return True
    except Exception:
        return False


def run_control_panel(*args: str) -> int:
    logs = logs_root()
    logs.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = logs / f"control-panel-run-{run_ts}.log"
    latest = logs / "control-panel-run.log"

    python_bin = _pick_python()

    with open(log_file, "w", encoding="utf-8") as log:
        script = project_root() / "src" / "sonolbot" / "core" / "daemon_control_panel.py"
        log.write(f"cmd={python_bin} {script} {' '.join(args)}\\n")
        log.write(f"cwd={project_root()}\\n")
        if not _check_tkinter(python_bin):
            print("[warn] tkinter might be unavailable for Windows GUI.")
        proc = subprocess.Popen(
            [python_bin, str(script), *args],
            cwd=str(project_root()),
            stdout=log,
            stderr=log,
        )
        rc = proc.wait()

    try:
        latest.write_text(log_file.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    return int(rc)


def build_control_panel_exe() -> int:
    if os.name != "nt":
        print("[error] build_control_panel_exe is Windows-only.")
        return 1

    root = project_root()
    python_bin = _pick_python()

    if shutil.which("pyinstaller") is None:
        pip = subprocess.run([python_bin, "-m", "pip", "install", "pyinstaller"], capture_output=True, text=True)
        if pip.returncode != 0:
            print("[error] pip install pyinstaller failed")
            return 1

    result = subprocess.run(
        [
            python_bin,
            "-m",
            "PyInstaller",
            "--onefile",
            "--noconsole",
            "--name",
            "control_panel",
            str(root / "src" / "sonolbot" / "core" / "control_panel_launcher.py"),
        ],
        cwd=str(root),
    )
    if result.returncode != 0:
        return int(result.returncode)

    src = root / "dist" / "control_panel.exe"
    dst = root / "control_panel.exe"
    if src.exists():
        shutil.copy2(src, dst)
        print(f"created {dst}")
        return 0
    print("[error] dist/control_panel.exe was not generated")
    return 1


def main() -> int:
    raise SystemExit("This module exports helper functions only.")
