"""Pure utility helpers for multi-bot manager."""

from __future__ import annotations

import re
import time
import os
from pathlib import Path
from typing import Any, Mapping


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, float(raw))
    except ValueError:
        return max(minimum, default)


def safe_bot_key(bot_id: str) -> str:
    val = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(bot_id or "").strip())
    return val or "unknown"


def normalize_allowed_users(raw_allowed_users: Any) -> list[int]:
    if not isinstance(raw_allowed_users, list):
        return []
    normalized: list[int] = []
    for item in raw_allowed_users:
        try:
            uid = int(item)
        except Exception:
            continue
        if uid > 0:
            normalized.append(uid)
    return normalized


def active_bots(cfg: Mapping[str, Any], normalized_allowed: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bots = cfg.get("bots")
    if not isinstance(bots, list):
        return out
    for row in bots:
        if not isinstance(row, dict):
            continue
        if not bool(row.get("active", False)):
            continue
        token = str(row.get("token") or "").strip()
        bot_id = str(row.get("bot_id") or "").strip()
        if not token or not bot_id:
            continue
        if not normalized_allowed:
            # Global allowed-users is required by current telegram skill contract.
            continue
        out.append(
            {
                "bot_id": bot_id,
                "token": token,
                "bot_username": str(row.get("bot_username") or "").strip(),
                "bot_name": str(row.get("bot_name") or "").strip(),
                "allowed_users_global": normalized_allowed,
            }
        )
    return out


def build_worker_env(
    *,
    bot: Mapping[str, Any],
    workspace: Path,
    config_path: Path,
    base_env: Mapping[str, str],
    rewriter_tmp_root: Path,
) -> dict[str, str]:
    env = dict(base_env)
    allowed_users = bot.get("allowed_users_global") or []
    allowed_raw = ",".join(str(int(v)) for v in allowed_users if int(v) > 0)

    logs_dir = workspace / "logs"
    tasks_dir = workspace / "tasks"
    messages_dir = workspace / "messages"
    state_dir = workspace / "state"

    env["DAEMON_BOT_WORKER"] = "1"
    env["SONOLBOT_MULTI_BOT_MANAGER"] = "0"
    env["SONOLBOT_BOT_ID"] = str(bot["bot_id"])
    env["SONOLBOT_BOT_WORKSPACE"] = str(workspace)
    env["SONOLBOT_BOTS_CONFIG"] = str(config_path)
    env["TELEGRAM_BOT_TOKEN"] = str(bot["token"])
    env["TELEGRAM_ALLOWED_USERS"] = allowed_raw
    env["TELEGRAM_USER_ID"] = str(allowed_users[0]) if allowed_users else ""

    env["WORK_DIR"] = str(workspace)
    env["LOGS_DIR"] = str(logs_dir)
    env["TASKS_DIR"] = str(tasks_dir)
    env["TELEGRAM_TASKS_DIR"] = str(tasks_dir)
    env["TELEGRAM_LOGS_DIR"] = str(logs_dir)
    env["TASKS_LOGS_DIR"] = str(logs_dir)
    env["TELEGRAM_MESSAGE_STORE"] = str(messages_dir / "telegram_messages.json")
    env["DAEMON_ACTIVITY_FILE"] = str(logs_dir / "codex-app-server.log")
    env["DAEMON_APP_SERVER_LOG_FILE"] = str(logs_dir / "codex-app-server.log")
    env["DAEMON_APP_SERVER_STATE_FILE"] = str(state_dir / "codex-app-session-state.json")
    env["DAEMON_AGENT_REWRITER_TMP_ROOT"] = str(rewriter_tmp_root)
    env["DAEMON_AGENT_REWRITER_WORKSPACE"] = str(
        rewriter_tmp_root / safe_bot_key(str(bot["bot_id"]))
    )
    env["DAEMON_AGENT_REWRITER_PID_FILE"] = str(state_dir / "codex-agent-rewriter.pid")
    env["DAEMON_AGENT_REWRITER_STATE_FILE"] = str(state_dir / "codex-agent-rewriter-state.json")
    env["DAEMON_AGENT_REWRITER_LOG_FILE"] = str(logs_dir / "codex-agent-rewriter.log")
    env["DAEMON_AGENT_REWRITER_LOCK_FILE"] = str(state_dir / "agent-rewriter.lock")
    env["DAEMON_PID_FILE"] = str(state_dir / "daemon-worker.pid")
    env["DAEMON_LOCK_FILE"] = str(state_dir / "daemon-worker.lock")
    env["CODEX_PID_FILE"] = str(state_dir / "codex-app-server.pid")
    env["SONOLBOT_TASKS_PARTITION_BY_CHAT"] = "1"
    return env


def update_restart_state(
    state: Mapping[str, Any],
    *,
    exit_code: int,
    runtime_sec: float,
    stable_reset_sec: float,
    base_backoff_sec: float,
    max_backoff_sec: float,
    now_epoch: float | None = None,
) -> tuple[int, float, float, dict[str, Any]]:
    now = time.time() if now_epoch is None else now_epoch
    state_payload = dict(state)
    fail_count = int(state_payload.get("fail_count") or 0)
    if (exit_code == 0) and (runtime_sec >= stable_reset_sec):
        fail_count = 0
        next_start_at = 0.0
        backoff_sec = 0.0
    else:
        fail_count += 1
        backoff_sec = min(max_backoff_sec, base_backoff_sec * (2 ** max(0, fail_count - 1)))
        next_start_at = now + backoff_sec
    state_payload["fail_count"] = fail_count
    state_payload["next_start_at"] = next_start_at
    state_payload["last_exit_rc"] = int(exit_code)
    state_payload["last_exit_at"] = now
    state_payload["last_skip_log_at"] = 0.0
    return fail_count, next_start_at, float(backoff_sec), state_payload


def can_start_worker_now(
    state: Mapping[str, Any],
    *,
    now_epoch: float,
    poll_interval_sec: float,
) -> tuple[bool, float, bool]:
    next_start_at = float(state.get("next_start_at") or 0.0)
    if next_start_at <= 0 or now_epoch >= next_start_at:
        return True, 0.0, False
    remaining = max(0.0, next_start_at - now_epoch)
    last_skip_log_at = float(state.get("last_skip_log_at") or 0.0)
    should_log = (now_epoch - last_skip_log_at) >= max(5.0, float(poll_interval_sec))
    return False, remaining, should_log


__all__ = [name for name in globals() if not name.startswith("__")]
