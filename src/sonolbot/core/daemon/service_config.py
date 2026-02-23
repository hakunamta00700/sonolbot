from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import re
from pathlib import Path
from typing import Any

from sonolbot.core.bot_config_store import default_config_path
from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.runtime_shared import CODEX_CLI_VERSION_UNKNOWN, PROJECT_ROOT
from sonolbot.core.daemon import constants as _constants


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    return _service_utils.env_int(name, default, minimum=minimum)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    return _service_utils.env_float(name, default, minimum=minimum)


def _env_bool(name: str, default: bool) -> bool:
    return _service_utils.env_bool(name, default)


def _normalize_telegram_parse_mode(parse_mode: object) -> str:
    return _service_utils.normalize_telegram_parse_mode(parse_mode)


def _format_default_str(value: str, default: str) -> str:
    return (value or "").strip() or default


@dataclass(slots=True)
class DaemonServiceConfig:
    root: Path
    logs_dir: Path
    tasks_dir: Path
    store_file: Path
    is_bot_worker: bool
    bot_id: str
    bot_workspace: Path
    codex_work_dir: Path
    bots_config_path: Path
    pid_file: Path
    lock_file: Path
    codex_pid_file: Path
    state_dir: Path
    app_server_lock_file: Path
    chat_locks_dir: Path
    activity_file: Path
    poll_interval_sec: int
    idle_timeout_sec: int
    log_retention_days: int
    activity_max_bytes: int
    activity_backup_count: int
    activity_retention_days: int
    codex_model: str
    codex_reasoning_effort: str
    fallback_send_max_attempts: int
    fallback_send_retry_delay_sec: float
    fallback_send_retry_backoff: float
    codex_cli_version: str
    codex_session_meta_file: Path
    tasks_partition_by_chat: bool
    app_server_listen: str
    app_server_progress_interval_sec: float
    app_server_steer_batch_window_ms: int
    app_server_turn_timeout_sec: int
    app_server_restart_backoff_sec: float
    app_server_request_timeout_sec: float
    app_server_approval_policy: str
    app_server_sandbox: str
    app_server_forward_agent_message: bool
    telegram_force_parse_mode: bool
    telegram_default_parse_mode: str
    telegram_parse_fallback_raw_on_fail: bool
    agent_rewriter_enabled: bool
    agent_rewriter_timeout_sec: float
    agent_rewriter_request_timeout_sec: float
    agent_rewriter_restart_backoff_sec: float
    agent_rewriter_max_retry: int
    agent_rewriter_model: str
    agent_rewriter_reasoning_effort: str
    agent_rewriter_tmp_root: Path
    agent_rewriter_cleanup_tmp: bool
    agent_rewriter_prompt_file: str
    agent_rewriter_prompt: str
    chat_lease_ttl_sec: float
    chat_lease_heartbeat_sec: float
    file_lock_wait_timeout_sec: float
    completed_message_ttl_sec: float
    ui_mode_timeout_sec: float
    new_task_summary_lines: int
    new_task_summary_max_chars: int
    task_search_llm_enabled: bool
    task_search_llm_limit: int
    task_search_llm_candidate_pool_limit: int
    task_search_llm_min_score: int
    task_search_llm_turn_timeout_sec: float
    task_search_llm_request_timeout_sec: float
    app_server_state_file: Path
    app_server_log_file: Path
    agent_rewriter_workspace: Path
    agent_rewriter_pid_file: Path
    agent_rewriter_state_file: Path
    agent_rewriter_log_file: Path
    agent_rewriter_lock_file: Path

    @classmethod
    def from_env(
        cls,
        root: Path | None = None,
    ) -> tuple["DaemonServiceConfig", list[str]]:
        base_root = Path(root or PROJECT_ROOT).resolve()
        warnings: list[str] = []

        logs_dir = Path(os.getenv("LOGS_DIR", str(base_root / "logs"))).resolve()
        tasks_dir = Path(os.getenv("TASKS_DIR", str(base_root / "tasks"))).resolve()
        store_file = Path(os.getenv("TELEGRAM_MESSAGE_STORE", str(base_root / "telegram_messages.json"))).resolve()
        is_bot_worker = (os.getenv("DAEMON_BOT_WORKER", "0").strip() == "1")
        bot_id = (os.getenv("SONOLBOT_BOT_ID", "") or "").strip()
        bot_workspace = Path(os.getenv("SONOLBOT_BOT_WORKSPACE", str(base_root))).resolve()
        codex_work_dir = (bot_workspace if is_bot_worker else base_root).resolve()
        bots_config_path = default_config_path(base_root)

        pid_file = Path(os.getenv("DAEMON_PID_FILE", str(base_root / ".daemon_service.pid"))).resolve()
        lock_file = Path(
            os.getenv("DAEMON_LOCK_FILE", str(pid_file.with_suffix(".lock")))
        ).resolve()
        codex_pid_file = Path(os.getenv("CODEX_PID_FILE", str(base_root / ".codex_app_server.pid"))).resolve()
        state_dir = codex_pid_file.parent.resolve()
        app_server_lock_file = Path(
            os.getenv("DAEMON_APP_SERVER_LOCK_FILE", str(state_dir / "app-server.lock"))
        ).resolve()
        chat_locks_dir = Path(
            os.getenv("DAEMON_CHAT_LOCKS_DIR", str(state_dir / "chat_locks"))
        ).resolve()
        activity_file = Path(
            os.getenv("DAEMON_ACTIVITY_FILE", str(logs_dir / "codex-app-server.log"))
        ).resolve()

        poll_interval_sec = _env_int("DAEMON_POLL_INTERVAL_SEC", 1, minimum=0)
        idle_timeout_sec = _env_int("DAEMON_IDLE_TIMEOUT_SEC", 600, minimum=0)
        log_retention_days = _env_int("LOG_RETENTION_DAYS", 7, minimum=1)
        activity_max_bytes = _env_int("DAEMON_ACTIVITY_MAX_BYTES", _constants.DEFAULT_ACTIVITY_MAX_BYTES, minimum=1)
        activity_backup_count = _env_int(
            "DAEMON_ACTIVITY_BACKUP_COUNT", _constants.DEFAULT_ACTIVITY_BACKUP_COUNT, minimum=0
        )
        activity_retention_days = _env_int(
            "DAEMON_ACTIVITY_RETENTION_DAYS", log_retention_days, minimum=1
        )
        codex_model = _format_default_str(os.getenv("SONOLBOT_CODEX_MODEL", ""), _constants.DEFAULT_CODEX_MODEL)
        codex_reasoning_effort = _format_default_str(
            os.getenv("SONOLBOT_CODEX_REASONING_EFFORT", ""), _constants.DEFAULT_CODEX_REASONING_EFFORT
        )
        fallback_send_max_attempts = _env_int(
            "DAEMON_FALLBACK_SEND_MAX_ATTEMPTS",
            _constants.DEFAULT_FALLBACK_SEND_MAX_ATTEMPTS,
            minimum=1,
        )
        fallback_send_retry_delay_sec = _env_float(
            "DAEMON_FALLBACK_SEND_RETRY_DELAY_SEC",
            _constants.DEFAULT_FALLBACK_SEND_RETRY_DELAY_SEC,
            minimum=0.05,
        )
        fallback_send_retry_backoff = _env_float(
            "DAEMON_FALLBACK_SEND_RETRY_BACKOFF",
            _constants.DEFAULT_FALLBACK_SEND_RETRY_BACKOFF,
            minimum=1.0,
        )
        codex_session_meta_file = logs_dir / "codex-session-current.json"
        tasks_partition_by_chat = _env_bool(
            "SONOLBOT_TASKS_PARTITION_BY_CHAT",
            _constants.DEFAULT_TASKS_PARTITION_BY_CHAT,
        )
        app_server_listen = _format_default_str(
            os.getenv("DAEMON_APP_SERVER_LISTEN", _constants.DEFAULT_APP_SERVER_LISTEN),
            _constants.DEFAULT_APP_SERVER_LISTEN,
        )
        app_server_progress_interval_sec = _env_float(
            "DAEMON_APP_SERVER_PROGRESS_INTERVAL_SEC",
            _constants.DEFAULT_APP_SERVER_PROGRESS_INTERVAL_SEC,
            minimum=5.0,
        )
        app_server_steer_batch_window_ms = _env_int(
            "DAEMON_APP_SERVER_STEER_BATCH_WINDOW_MS",
            _constants.DEFAULT_APP_SERVER_STEER_BATCH_WINDOW_MS,
            minimum=100,
        )
        app_server_turn_timeout_sec = _env_int(
            "DAEMON_APP_SERVER_TURN_TIMEOUT_SEC",
            _constants.DEFAULT_APP_SERVER_TURN_TIMEOUT_SEC,
            minimum=60,
        )
        app_server_restart_backoff_sec = _env_float(
            "DAEMON_APP_SERVER_RESTART_BACKOFF_SEC",
            _constants.DEFAULT_APP_SERVER_RESTART_BACKOFF_SEC,
            minimum=0.5,
        )
        app_server_request_timeout_sec = _env_float(
            "DAEMON_APP_SERVER_REQUEST_TIMEOUT_SEC",
            _constants.DEFAULT_APP_SERVER_REQUEST_TIMEOUT_SEC,
            minimum=5.0,
        )
        app_server_approval_policy = _format_default_str(
            os.getenv("DAEMON_APP_SERVER_APPROVAL_POLICY", _constants.DEFAULT_APP_SERVER_APPROVAL_POLICY),
            _constants.DEFAULT_APP_SERVER_APPROVAL_POLICY,
        )
        app_server_sandbox = _format_default_str(
            os.getenv("DAEMON_APP_SERVER_SANDBOX", _constants.DEFAULT_APP_SERVER_SANDBOX),
            _constants.DEFAULT_APP_SERVER_SANDBOX,
        )
        app_server_forward_agent_message = _env_bool(
            "DAEMON_APP_SERVER_FORWARD_AGENT_MESSAGE",
            _constants.DEFAULT_APP_SERVER_FORWARD_AGENT_MESSAGE,
        )
        telegram_force_parse_mode = _env_bool(
            "DAEMON_TELEGRAM_FORCE_PARSE_MODE",
            _constants.DEFAULT_TELEGRAM_FORCE_PARSE_MODE,
        )

        telegram_default_parse_raw = os.getenv(
            "DAEMON_TELEGRAM_DEFAULT_PARSE_MODE",
            _constants.DEFAULT_TELEGRAM_DEFAULT_PARSE_MODE,
        ).strip()
        telegram_default_parse_mode = _normalize_telegram_parse_mode(telegram_default_parse_raw)
        if not telegram_default_parse_mode and telegram_default_parse_raw:
            warnings.append(
                f"invalid DAEMON_TELEGRAM_DEFAULT_PARSE_MODE={telegram_default_parse_raw!r}; "
                f"fallback={_constants.DEFAULT_TELEGRAM_DEFAULT_PARSE_MODE}"
            )
            telegram_default_parse_mode = _constants.DEFAULT_TELEGRAM_DEFAULT_PARSE_MODE
        elif not telegram_default_parse_mode:
            telegram_default_parse_mode = _constants.DEFAULT_TELEGRAM_DEFAULT_PARSE_MODE

        telegram_parse_fallback_raw_on_fail = _env_bool(
            "DAEMON_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL",
            _constants.DEFAULT_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL,
        )
        agent_rewriter_enabled = _env_bool(
            "DAEMON_AGENT_REWRITER_ENABLED",
            _constants.DEFAULT_AGENT_REWRITER_ENABLED,
        )
        agent_rewriter_timeout_sec = _env_float(
            "DAEMON_AGENT_REWRITER_TIMEOUT_SEC",
            _constants.DEFAULT_AGENT_REWRITER_TIMEOUT_SEC,
            minimum=2.0,
        )
        agent_rewriter_request_timeout_sec = _env_float(
            "DAEMON_AGENT_REWRITER_REQUEST_TIMEOUT_SEC",
            _constants.DEFAULT_AGENT_REWRITER_REQUEST_TIMEOUT_SEC,
            minimum=3.0,
        )
        agent_rewriter_restart_backoff_sec = _env_float(
            "DAEMON_AGENT_REWRITER_RESTART_BACKOFF_SEC",
            _constants.DEFAULT_AGENT_REWRITER_RESTART_BACKOFF_SEC,
            minimum=0.5,
        )
        agent_rewriter_max_retry = _env_int(
            "DAEMON_AGENT_REWRITER_MAX_RETRY",
            _constants.DEFAULT_AGENT_REWRITER_MAX_RETRY,
            minimum=0,
        )
        agent_rewriter_tmp_root = Path(
            os.getenv(
                "DAEMON_AGENT_REWRITER_TMP_ROOT",
                _constants.DEFAULT_AGENT_REWRITER_TMP_ROOT,
            )
        ).expanduser().resolve()
        agent_rewriter_model = _format_default_str(
            os.getenv("DAEMON_AGENT_REWRITER_MODEL", _constants.DEFAULT_AGENT_REWRITER_MODEL),
            codex_model,
        )
        agent_rewriter_reasoning_effort = _format_default_str(
            os.getenv("DAEMON_AGENT_REWRITER_REASONING_EFFORT", _constants.DEFAULT_AGENT_REWRITER_REASONING_EFFORT),
            _constants.DEFAULT_AGENT_REWRITER_REASONING_EFFORT,
        )
        agent_rewriter_cleanup_tmp = _env_bool(
            "DAEMON_AGENT_REWRITER_CLEANUP_TMP",
            _constants.DEFAULT_AGENT_REWRITER_CLEANUP_TMP,
        )
        agent_rewriter_prompt_file = os.getenv("DAEMON_AGENT_REWRITER_PROMPT_FILE", "").strip()
        agent_rewriter_prompt: str = ""
        if agent_rewriter_prompt_file:
            try:
                prompt_path = Path(agent_rewriter_prompt_file).expanduser().resolve()
                agent_rewriter_prompt = prompt_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                warnings.append(
                    f"failed to load DAEMON_AGENT_REWRITER_PROMPT_FILE={agent_rewriter_prompt_file}: {exc}"
                )
        if not agent_rewriter_prompt:
            prompt_raw = os.getenv(
                "DAEMON_AGENT_REWRITER_PROMPT", _constants.DEFAULT_AGENT_REWRITER_PROMPT
            )
            agent_rewriter_prompt = str(prompt_raw or _constants.DEFAULT_AGENT_REWRITER_PROMPT).replace(
                "\\n", "\n"
            ).strip()
        if not agent_rewriter_prompt:
            agent_rewriter_prompt = _constants.DEFAULT_AGENT_REWRITER_PROMPT

        chat_lease_ttl_sec = _env_float(
            "DAEMON_CHAT_LEASE_TTL_SEC",
            _constants.DEFAULT_CHAT_LEASE_TTL_SEC,
            minimum=30.0,
        )
        chat_lease_heartbeat_sec = _env_float(
            "DAEMON_CHAT_LEASE_HEARTBEAT_SEC",
            _constants.DEFAULT_CHAT_LEASE_HEARTBEAT_SEC,
            minimum=5.0,
        )
        if chat_lease_heartbeat_sec > chat_lease_ttl_sec:
            chat_lease_heartbeat_sec = max(5.0, chat_lease_ttl_sec / 2.0)

        file_lock_wait_timeout_sec = _env_float(
            "DAEMON_FILE_LOCK_WAIT_TIMEOUT_SEC",
            _constants.DEFAULT_FILE_LOCK_WAIT_TIMEOUT_SEC,
            minimum=0.2,
        )
        completed_message_ttl_sec = _env_float(
            "DAEMON_COMPLETED_MESSAGE_TTL_SEC",
            _constants.DEFAULT_COMPLETED_MESSAGE_TTL_SEC,
            minimum=30.0,
        )
        ui_mode_timeout_sec = _env_float(
            "DAEMON_UI_MODE_TIMEOUT_SEC",
            _constants.DEFAULT_UI_MODE_TIMEOUT_SEC,
            minimum=30.0,
        )
        new_task_summary_lines = _env_int(
            "DAEMON_NEW_TASK_SUMMARY_LINES",
            _constants.DEFAULT_NEW_TASK_SUMMARY_LINES,
            minimum=10,
        )
        new_task_summary_max_chars = _env_int(
            "DAEMON_NEW_TASK_SUMMARY_MAX_CHARS",
            _constants.DEFAULT_NEW_TASK_SUMMARY_MAX_CHARS,
            minimum=1200,
        )
        task_search_llm_enabled = _env_bool(
            "DAEMON_TASK_SEARCH_LLM_ENABLED",
            _constants.DEFAULT_TASK_SEARCH_LLM_ENABLED,
        )
        task_search_llm_limit = _env_int(
            "DAEMON_TASK_SEARCH_LLM_LIMIT",
            _constants.DEFAULT_TASK_SEARCH_LLM_LIMIT,
            minimum=1,
        )
        task_search_llm_candidate_pool_limit = _env_int(
            "DAEMON_TASK_SEARCH_LLM_CANDIDATE_POOL_LIMIT",
            _constants.DEFAULT_TASK_SEARCH_LLM_CANDIDATE_POOL_LIMIT,
            minimum=10,
        )
        task_search_llm_min_score = _env_int(
            "DAEMON_TASK_SEARCH_LLM_MIN_SCORE",
            _constants.DEFAULT_TASK_SEARCH_LLM_MIN_SCORE,
            minimum=0,
        )
        if task_search_llm_min_score > 100:
            task_search_llm_min_score = 100
        task_search_llm_turn_timeout_sec = _env_float(
            "DAEMON_TASK_SEARCH_LLM_TURN_TIMEOUT_SEC",
            _constants.DEFAULT_TASK_SEARCH_LLM_TURN_TIMEOUT_SEC,
            minimum=5.0,
        )
        task_search_llm_request_timeout_sec = _env_float(
            "DAEMON_TASK_SEARCH_LLM_REQUEST_TIMEOUT_SEC",
            _constants.DEFAULT_TASK_SEARCH_LLM_REQUEST_TIMEOUT_SEC,
            minimum=5.0,
        )
        app_server_state_file = Path(
            os.getenv("DAEMON_APP_SERVER_STATE_FILE", str(logs_dir / "codex-app-session-state.json"))
        ).resolve()
        app_server_log_file = Path(
            os.getenv("DAEMON_APP_SERVER_LOG_FILE", str(logs_dir / "codex-app-server.log"))
        ).resolve()

        rewriter_workspace_raw = os.getenv("DAEMON_AGENT_REWRITER_WORKSPACE", "").strip()
        if rewriter_workspace_raw:
            workspace_raw = rewriter_workspace_raw
        elif is_bot_worker and bot_id:
            bot_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(bot_id).strip()) or "unknown"
            workspace_raw = str(agent_rewriter_tmp_root / bot_key)
        else:
            workspace_raw = str(state_dir / "agent-rewriter-workspace")
        agent_rewriter_workspace = Path(workspace_raw).resolve()

        agent_rewriter_pid_file = Path(
            os.getenv("DAEMON_AGENT_REWRITER_PID_FILE", str(state_dir / "codex-agent-rewriter.pid"))
        ).resolve()
        agent_rewriter_state_file = Path(
            os.getenv(
                "DAEMON_AGENT_REWRITER_STATE_FILE",
                str(state_dir / "codex-agent-rewriter-state.json"),
            )
        ).resolve()
        agent_rewriter_log_file = Path(
            os.getenv("DAEMON_AGENT_REWRITER_LOG_FILE", str(logs_dir / "codex-agent-rewriter.log"))
        ).resolve()
        agent_rewriter_lock_file = Path(
            os.getenv("DAEMON_AGENT_REWRITER_LOCK_FILE", str(state_dir / "agent-rewriter.lock"))
        ).resolve()

        config = cls(
            root=base_root,
            logs_dir=logs_dir,
            tasks_dir=tasks_dir,
            store_file=store_file,
            is_bot_worker=is_bot_worker,
            bot_id=bot_id,
            bot_workspace=bot_workspace,
            codex_work_dir=codex_work_dir,
            bots_config_path=bots_config_path,
            pid_file=pid_file,
            lock_file=lock_file,
            codex_pid_file=codex_pid_file,
            state_dir=state_dir,
            app_server_lock_file=app_server_lock_file,
            chat_locks_dir=chat_locks_dir,
            activity_file=activity_file,
            poll_interval_sec=poll_interval_sec,
            idle_timeout_sec=idle_timeout_sec,
            log_retention_days=log_retention_days,
            activity_max_bytes=activity_max_bytes,
            activity_backup_count=activity_backup_count,
            activity_retention_days=activity_retention_days,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            fallback_send_max_attempts=fallback_send_max_attempts,
            fallback_send_retry_delay_sec=fallback_send_retry_delay_sec,
            fallback_send_retry_backoff=fallback_send_retry_backoff,
            codex_cli_version=CODEX_CLI_VERSION_UNKNOWN,
            codex_session_meta_file=codex_session_meta_file,
            tasks_partition_by_chat=tasks_partition_by_chat,
            app_server_listen=app_server_listen,
            app_server_progress_interval_sec=app_server_progress_interval_sec,
            app_server_steer_batch_window_ms=app_server_steer_batch_window_ms,
            app_server_turn_timeout_sec=app_server_turn_timeout_sec,
            app_server_restart_backoff_sec=app_server_restart_backoff_sec,
            app_server_request_timeout_sec=app_server_request_timeout_sec,
            app_server_approval_policy=app_server_approval_policy,
            app_server_sandbox=app_server_sandbox,
            app_server_forward_agent_message=app_server_forward_agent_message,
            telegram_force_parse_mode=telegram_force_parse_mode,
            telegram_default_parse_mode=telegram_default_parse_mode,
            telegram_parse_fallback_raw_on_fail=telegram_parse_fallback_raw_on_fail,
            agent_rewriter_enabled=agent_rewriter_enabled,
            agent_rewriter_timeout_sec=agent_rewriter_timeout_sec,
            agent_rewriter_request_timeout_sec=agent_rewriter_request_timeout_sec,
            agent_rewriter_restart_backoff_sec=agent_rewriter_restart_backoff_sec,
            agent_rewriter_max_retry=agent_rewriter_max_retry,
            agent_rewriter_model=agent_rewriter_model,
            agent_rewriter_reasoning_effort=agent_rewriter_reasoning_effort,
            agent_rewriter_tmp_root=agent_rewriter_tmp_root,
            agent_rewriter_cleanup_tmp=agent_rewriter_cleanup_tmp,
            agent_rewriter_prompt_file=agent_rewriter_prompt_file,
            agent_rewriter_prompt=agent_rewriter_prompt,
            chat_lease_ttl_sec=chat_lease_ttl_sec,
            chat_lease_heartbeat_sec=chat_lease_heartbeat_sec,
            file_lock_wait_timeout_sec=file_lock_wait_timeout_sec,
            completed_message_ttl_sec=completed_message_ttl_sec,
            ui_mode_timeout_sec=ui_mode_timeout_sec,
            new_task_summary_lines=new_task_summary_lines,
            new_task_summary_max_chars=new_task_summary_max_chars,
            task_search_llm_enabled=task_search_llm_enabled,
            task_search_llm_limit=task_search_llm_limit,
            task_search_llm_candidate_pool_limit=task_search_llm_candidate_pool_limit,
            task_search_llm_min_score=task_search_llm_min_score,
            task_search_llm_turn_timeout_sec=task_search_llm_turn_timeout_sec,
            task_search_llm_request_timeout_sec=task_search_llm_request_timeout_sec,
            app_server_state_file=app_server_state_file,
            app_server_log_file=app_server_log_file,
            agent_rewriter_workspace=agent_rewriter_workspace,
            agent_rewriter_pid_file=agent_rewriter_pid_file,
            agent_rewriter_state_file=agent_rewriter_state_file,
            agent_rewriter_log_file=agent_rewriter_log_file,
            agent_rewriter_lock_file=agent_rewriter_lock_file,
        )
        return config, warnings

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
