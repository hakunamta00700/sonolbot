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

load_dotenv(PROJECT_ROOT / ".env", override=False)

__all__ = [name for name in globals() if not name.startswith("__")]
