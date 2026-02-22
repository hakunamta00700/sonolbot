#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill-only quick checker for Telegram pending messages.

Exit code:
- 0: no pending user messages
- 1: pending user messages exist
- 2: error
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from skill_bridge import build_telegram_runtime, get_telegram_skill


def main() -> int:
    root = Path(__file__).resolve().parent
    store_path = Path(os.getenv("TELEGRAM_MESSAGE_STORE", str(root / "telegram_messages.json"))).resolve()

    runtime = build_telegram_runtime()
    telegram = get_telegram_skill()
    _, pending, _ = telegram.poll_store_and_get_pending(
        runtime=runtime,
        store_path=str(store_path),
        include_bot=False,
    )

    print(f"[QUICK_CHECK] pending={len(pending)} store={store_path}")
    return 1 if pending else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[QUICK_CHECK][ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
