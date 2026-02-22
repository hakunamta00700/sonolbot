"""Python implementation that replaces setup_wsl.sh."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

from sonolbot.runtime import project_root

ROOT = project_root()
ENV_FILE = ROOT / ".env"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS_FILE = ROOT / "requirements.txt"

DEFAULT_ENV = [
    ("SONOLBOT_ALLOWED_SKILLS", "sonolbot-telegram,sonolbot-tasks"),
    ("SONOLBOT_MULTI_BOT_MANAGER", "1"),
    ("SONOLBOT_BOT_WORKSPACES_DIR", "bots"),
    ("SONOLBOT_BOTS_CONFIG", ".control_panel_telegram_bots.json"),
    ("TELEGRAM_POLLING_INTERVAL", "1"),
    ("TELEGRAM_API_TIMEOUT_SEC", "20"),
    ("TELEGRAM_MAX_FILE_BYTES", "52428800"),
    ("TELEGRAM_MESSAGE_RETENTION_DAYS", "7"),
    ("TELEGRAM_INCLUDE_24H_CONTEXT", "1"),
    ("TASKS_DIR", "tasks"),
    ("LOGS_DIR", "logs"),
    ("DAEMON_POLL_INTERVAL_SEC", "1"),
    ("DAEMON_IDLE_TIMEOUT_SEC", "600"),
    ("DAEMON_ACTIVITY_FILE", "logs/codex-app-server.log"),
    ("DAEMON_ACTIVITY_MAX_BYTES", "10485760"),
    ("DAEMON_ACTIVITY_BACKUP_COUNT", "7"),
    ("DAEMON_ACTIVITY_RETENTION_DAYS", "7"),
    ("LOG_RETENTION_DAYS", "7"),
    ("DAEMON_TELEGRAM_FORCE_PARSE_MODE", "1"),
    ("DAEMON_TELEGRAM_DEFAULT_PARSE_MODE", "HTML"),
    ("DAEMON_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL", "1"),
    ("DAEMON_AGENT_REWRITER_ENABLED", "1"),
    ("DAEMON_AGENT_REWRITER_MODEL", "gpt-5.3-codex"),
    ("DAEMON_AGENT_REWRITER_TMP_ROOT", "/tmp/sonolbot-agent-rewriter"),
    ("DAEMON_AGENT_REWRITER_CLEANUP_TMP", "1"),
    ("DAEMON_AGENT_REWRITER_REASONING_EFFORT", "none"),
    ("DAEMON_AGENT_REWRITER_TIMEOUT_SEC", "40"),
    ("DAEMON_AGENT_REWRITER_REQUEST_TIMEOUT_SEC", "30"),
    ("DAEMON_AGENT_REWRITER_MAX_RETRY", "1"),
    ("DAEMON_AGENT_REWRITER_RESTART_BACKOFF_SEC", "2"),
    ("SONOLBOT_STORE_CODEX_SESSION", "1"),
]


def _has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str], check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _install_via_apt(pkgs: Iterable[str]) -> bool:
    if not os.path.exists("/usr/bin/apt-get"):
        return False
    try:
        _run(["sudo", "apt-get", "update"], check=False)
        _run(["sudo", "apt-get", "install", "-y", *pkgs], check=True)
        return True
    except Exception:
        return False


def _check_or_install(cmd: str, pkg: str, auto_install: bool) -> bool:
    if _has_command(cmd):
        return True
    if not auto_install:
        return False
    return _install_via_apt([pkg])


def _ensure_python(auto_apt_install: bool) -> bool:
    ok = _check_or_install("python3", "python3", auto_apt_install)
    if not ok:
        return False
    try:
        _run(["python3", "-m", "pip", "--version"])
        ok = True
    except Exception:
        ok = _check_or_install("python3-pip", "python3-pip", auto_apt_install)
    if ok:
        _run(["python3", "-m", "venv", "--help"])
    return ok


def _ensure_tkinter(auto_apt_install: bool) -> bool:
    try:
        _run(["python3", "- <<'PY'\nimport tkinter\nPY"], check=True)
        return True
    except Exception:
        if not auto_apt_install:
            return False
        return _check_or_install("python3-tk", "python3-tk", auto_apt_install)


def _ensure_node_and_codex(auto_apt_install: bool) -> bool:
    ok_node = _has_command("node")
    ok_npm = _has_command("npm")
    if not (ok_node and ok_npm):
        if auto_apt_install:
            ok_node = _check_or_install("node", "nodejs", True)
            ok_npm = _check_or_install("npm", "npm", True)
    if not (ok_node and ok_npm):
        return False
    if not _has_command("codex"):
        return False
    try:
        _run(["codex", "--version"])
    except Exception:
        return False
    return True


def _ensure_default_env(root: Path) -> None:
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            existing[k.strip()] = v.strip()

    for key, value in DEFAULT_ENV:
        existing.setdefault(key, value)

    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass


def run_setup_wsl(
    *,
    auto_apt_install: bool = False,
    skip_env: bool = False,
) -> int:
    root = ROOT
    setup_noninteractive = os.getenv("SONOLBOT_SETUP_NONINTERACTIVE", "0") == "1"

    print("=" * 40)
    print("Sonolbot WSL + Codex setup")
    print("=" * 40)
    print(f"Workspace: {root}")
    print()

    print("[1/3] prerequisite check")
    python_ok = _ensure_python(auto_apt_install)
    tkinter_ok = _ensure_tkinter(auto_apt_install)
    node_ok = _ensure_node_and_codex(auto_apt_install)

    if not (python_ok and node_ok):
        if not setup_noninteractive:
            print("[warn] prerequisites are not fully satisfied.")
        return 1

    print("  - python: ", "ok" if python_ok else "missing")
    print("  - tkinter:", "ok" if tkinter_ok else "not checked/optional for WSL")
    print("  - node/npm/codex:", "ok" if node_ok else "missing")

    print("[2/3] install python dependencies")
    VENV_DIR.mkdir(parents=True, exist_ok=True)
    if not VENV_PYTHON.exists():
        try:
            _run(["python3", "-m", "venv", str(VENV_DIR)])
        except Exception as exc:
            print(f"[error] failed to create venv: {exc}")
            return 1

    try:
        _run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
        _run([str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
    except Exception as exc:
        print(f"[error] dependency install failed: {exc}")
        return 1

    print("[3/3] .env")
    if not skip_env:
        _ensure_default_env(root)
        print(f"  - .env updated: {ENV_FILE}")

    print("Setup complete")
    return 0


def main() -> int:
    auto_apt = os.getenv("SONOLBOT_SETUP_AUTO_APT_INSTALL", "0") == "1"
    skip_env = os.getenv("SONOLBOT_SETUP_SKIP_ENV", "0") == "1"
    return run_setup_wsl(auto_apt_install=auto_apt, skip_env=skip_env)


if __name__ == "__main__":
    raise SystemExit(main())
