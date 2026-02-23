"""Daemon entrypoint."""
from __future__ import annotations

import os

from sonolbot.core.daemon.manager import MultiBotManager
from sonolbot.core.daemon.runtime_shared import DEFAULT_MULTI_BOT_MANAGER_ENABLED
from sonolbot.core.daemon.service import DaemonService


def main() -> int:
    if os.getenv("DAEMON_BOT_WORKER", "0").strip() == "1":
        service = DaemonService()
        return service.run()
    manager_enabled_raw = os.getenv("SONOLBOT_MULTI_BOT_MANAGER", "")
    if manager_enabled_raw.strip():
        manager_enabled = manager_enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        manager_enabled = DEFAULT_MULTI_BOT_MANAGER_ENABLED
    if manager_enabled:
        return MultiBotManager().run()
    return DaemonService().run()


if __name__ == "__main__":
    raise SystemExit(main())
