from __future__ import annotations

import html
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import shutil
from dotenv import load_dotenv
from sonolbot.core.daemon.constants import *
from sonolbot.core.daemon.locking import _is_pid_alive, _ProcessFileLock
from sonolbot.core.bot_config_store import (
    default_config_path,
    load_config as load_bots_config,
    migrate_legacy_env_if_needed,
    save_config as save_bots_config,
)
from sonolbot.core.skill_bridge import build_telegram_runtime, get_task_skill, get_telegram_skill
from sonolbot.runtime import project_root

PROJECT_ROOT = project_root()

CORE_ROOT = PROJECT_ROOT / "src" / "sonolbot" / "core"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from loguru import logger as _loguru_logger
except Exception:  # pragma: no cover
    import logging

    class _LoguruFallbackLogger:
        _logger = logging.getLogger("sonolbot.daemon")

        def add(self, *_args: object, **_kwargs: object) -> int:
            return -1

        def info(self, message: str) -> None:
            self._logger.info(message)

        def warning(self, message: str) -> None:
            self._logger.warning(message)

        def error(self, message: str) -> None:
            self._logger.error(message)

        def bind(self, *_args: object, **_kwargs: object) -> "_LoguruFallbackLogger":
            return self

        def log(self, level: str, message: str) -> None:
            if level.upper() == "WARNING":
                self._logger.warning(message)
            elif level.upper() in {"ERROR", "CRITICAL"}:
                self._logger.error(message)
            else:
                self._logger.info(message)

    _loguru_logger = _LoguruFallbackLogger()

    if not _LoguruFallbackLogger._logger.handlers:
        logging.basicConfig(level=logging.INFO, format="[daemon] %(asctime)s %(levelname)s: %(message)s")


_LOGURU_FILE_SINKS: set[str] = set()


def _ensure_daemon_log_sink(log_path: Path, component: str) -> None:
    path_key = f"{str(log_path)}|{component}"
    if path_key in _LOGURU_FILE_SINKS:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _loguru_logger.add(
            str(log_path),
            level="INFO",
            format=f"[{component}] [{{time:YYYY-MM-DD HH:mm:ss}}] {{level}} {{message}}",
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )
        _LOGURU_FILE_SINKS.add(path_key)
    except Exception:
        _LOGURU_FILE_SINKS.add(path_key)


def _log_with_loguru(
    message: str,
    *,
    log_path: Path,
    component: str = "daemon",
    level: str = "INFO",
) -> None:
    message_text = str(message).strip()
    if not message_text:
        return
    level_name = str(level).upper()
    if message_text.startswith("ERROR:"):
        level_name = "ERROR"
    elif message_text.startswith("WARN:"):
        level_name = "WARNING"
    elif message_text.startswith("INFO:"):
        level_name = "INFO"
    try:
        _ensure_daemon_log_sink(
            log_path=log_path,
            component=component,
        )
        level_name = str(level_name).upper()
        if hasattr(_loguru_logger, level_name.lower()):
            getattr(_loguru_logger, level_name.lower())(message_text)
            return
        _loguru_logger.log(level_name, message_text)
    except Exception:
        try:
            print(message_text)
        except Exception:
            pass

load_dotenv(PROJECT_ROOT / ".env", override=False)

__all__ = [name for name in globals() if not name.startswith("__")]
