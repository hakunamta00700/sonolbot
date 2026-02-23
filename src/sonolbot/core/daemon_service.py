#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility wrapper for daemon_service entrypoint."""

from __future__ import annotations

import sys
from sonolbot.runtime import project_root

PROJECT_ROOT = project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon.manager import MultiBotManager
from sonolbot.core.daemon.service import DaemonService
from sonolbot.core.daemon.main import main

if __name__ == "__main__":
    raise SystemExit(main())
