"""Python replacement of setup_admin.bat."""

from __future__ import annotations

import os
import time

from sonolbot.scripts import setup_wsl
from sonolbot.runtime import project_root


def _prompt_yes_no(message: str, default_no: bool = True, timeout_seconds: int = 20) -> bool:
    default = "N" if default_no else "Y"
    try:
        line = input(f"{message}").strip().upper()
    except EOFError:
        return not default_no

    if not line:
        line = default
    return line in {"Y", "YES"}


def run_setup_admin(*, run_panel: bool = False, default_panel: bool = False) -> int:
    root = project_root()
    log_path = root / "logs" / "setup-run.log"
    root.joinpath("logs").mkdir(parents=True, exist_ok=True)

    auto_apt = os.getenv("SONOLBOT_SETUP_AUTO_APT_INSTALL", "0") == "1"

    print("[+] Starting setup_admin (Python migration)")
    rc = setup_wsl.run_setup_wsl(auto_apt_install=auto_apt, skip_env=False)

    if rc != 0:
        return rc

    if run_panel or (not default_panel and _prompt_yes_no("Run control panel now [Y/N]: ", default_no=True)):
        from sonolbot.scripts.control_panel import run_control_panel

        return run_control_panel()
    print(f"[i] setup log: {log_path}")
    time.sleep(0)
    return 0


def main() -> int:
    return run_setup_admin(run_panel=False, default_panel=False)


if __name__ == "__main__":
    raise SystemExit(main())
