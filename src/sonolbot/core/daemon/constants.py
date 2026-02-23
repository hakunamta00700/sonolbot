"""Shared constants for daemon/service modules."""

from __future__ import annotations

import re
from pathlib import Path

PROMPT_TEXT_BACKUP = """
sonolbot-telegram 스킬로 새메시지(RECEIVE_FROM_TELEGRAM_NEWMSG) 확인하면 먼저 텔레그램으로 확인했다는 메시지부터 보낼것(SEND_TO_TELEGRAM_MSG), 존재하는 경우 그 작업(RECEIVE_FROM_TELEGRAM_NEWMSG)을 처리할 것.
RECEIVE_FROM_TELEGRAM_NEWMSG은 사용자의 지시이니 잘듣고 따를것.
RECEIVE_FROM_TELEGRAM_NEWMSG를 처리하는 중 사용자가 꼭 알아야 한다고 느끼는 중요한 점 있으면 텔레그램으로 보낼 것(SEND_TO_TELEGRAM_MSG)

SEND_TO_TELEGRAM_MSG 시마다 텔레그램으로부터 RECEIVE_FROM_TELEGRAM_NEWMSG를 확인하여, 
RECEIVE_FROM_TELEGRAM_NEWMSG이 존재하면, 사용자의 추가 지시이니 잘듣고 따를 것
RECEIVE_FROM_TELEGRAM_NEWMSG에 따라 작업을 처음 시작할 때, sonolbot-tasks 스킬 원칙을 따라 tasks 폴더에 새 작업을 만들 것 (sonolbot-tasks 스킬 사용).

중요 실행 원칙:
1) sonolbot-telegram + sonolbot-tasks 스킬 사용 
2) 수신은 허용 사용자 필터를 적용하고, 텍스트/파일/이미지/위치/음성/비디오를 처리할 것.
3) 로그는 logs 폴더(환경변수 LOGS_DIR/TELEGRAM_LOGS_DIR/TASKS_LOGS_DIR 반영)로 기록하고 7일 보관을 유지할 것.
4) TASK 생성 또는 선택후, INSTRUNCTION.md를 먼저 읽으며, 작업 변경 사항은 즉시 동기화할 것 (sonolbot-task 스킬 참조).
5) SEND_TO_TELEGRAM_MSG는 양식이 정해져 있지 않으니, 사용자에게 필요한 사항을 너가 판단하여 보내되, 알기 쉽게 설명할 것
"""

PROMPT_TEXT = ""

SECURE_FILE_MODE = 0o600
SECURE_DIR_MODE = 0o700

DEFAULT_ACTIVITY_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_ACTIVITY_BACKUP_COUNT = 7
DEFAULT_CODEX_MODEL = "gpt-5.3-codex"
DEFAULT_CODEX_REASONING_EFFORT = "high"
CODEX_CLI_VERSION_UNKNOWN = "unknown"
DEFAULT_FALLBACK_SEND_MAX_ATTEMPTS = 4
DEFAULT_FALLBACK_SEND_RETRY_DELAY_SEC = 1.0
DEFAULT_FALLBACK_SEND_RETRY_BACKOFF = 1.8

DEFAULT_CODEX_TRANSPORT_MODE = "app_server"
DEFAULT_APP_SERVER_LISTEN = "stdio://"
DEFAULT_APP_SERVER_PROGRESS_INTERVAL_SEC = 20.0
DEFAULT_APP_SERVER_STEER_BATCH_WINDOW_MS = 800
DEFAULT_APP_SERVER_TURN_TIMEOUT_SEC = 1800
DEFAULT_APP_SERVER_RESTART_BACKOFF_SEC = 3.0
DEFAULT_APP_SERVER_REQUEST_TIMEOUT_SEC = 45.0
DEFAULT_APP_SERVER_APPROVAL_POLICY = "on-request"
DEFAULT_APP_SERVER_SANDBOX = "workspace-write"
DEFAULT_APP_SERVER_FORWARD_AGENT_MESSAGE = True

DEFAULT_TELEGRAM_FORCE_PARSE_MODE = True
DEFAULT_TELEGRAM_DEFAULT_PARSE_MODE = "HTML"
DEFAULT_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL = True

DEFAULT_AGENT_REWRITER_ENABLED = True
DEFAULT_AGENT_REWRITER_TIMEOUT_SEC = 40.0
DEFAULT_AGENT_REWRITER_MAX_RETRY = 1
DEFAULT_AGENT_REWRITER_MODEL = "gpt-5.3-codex"
DEFAULT_AGENT_REWRITER_REASONING_EFFORT = "none"
DEFAULT_AGENT_REWRITER_REQUEST_TIMEOUT_SEC = 30.0
DEFAULT_AGENT_REWRITER_RESTART_BACKOFF_SEC = 2.0
DEFAULT_AGENT_REWRITER_TMP_ROOT = "/tmp/sonolbot-agent-rewriter"
DEFAULT_AGENT_REWRITER_CLEANUP_TMP = True
DEFAULT_AGENT_REWRITER_PROMPT = (
    "당신은 텔레그램 사용자에게 보여줄 중간 진행 안내문 재작성 전용 어시스턴트다.\\n"
    "목표: 원문의 의미를 유지하면서 사용자 친화적인 한국어 안내문으로 바꿔라.\\n"
    "출력 규칙:\\n"
    "1) 1~3문장으로 작성하되, 사용자가 현재 무엇을 진행 중인지 이해할 수 있을 만큼 구체적으로 쓸 것.\\n"
    "2) 내부 기술/구조/운영 용어를 절대 노출하지 말 것.\\n"
    "   금지 예: thread, msg_번호, INSTRUNCTION.md, index.json, task_meta, 동기화, 세션, 백그라운드, 스크립트, 명령어.\\n"
    "3) 시스템 파일/규칙/로그/프롬프트/도구 호출 사실을 언급하지 말 것.\\n"
    "4) 결과는 설명문만 출력하고, 머리말/꼬리말/코드블록/불릿은 사용하지 말 것.\\n"
    "5) 텔레그램 HTML 파싱 기준으로 작성하고, 강조가 필요하면 <b>와 <code>만 최소한으로 사용하라.\\n"
    "   Markdown 문법(*, _, #, ``` 등)은 사용하지 말 것.\\n"
)

DEFAULT_TASKS_PARTITION_BY_CHAT = True
DEFAULT_MULTI_BOT_MANAGER_ENABLED = True
DEFAULT_BOT_WORKSPACE_DIRNAME = "bots"

DEFAULT_WORKER_RESTART_BASE_SEC = 5.0
DEFAULT_WORKER_RESTART_MAX_SEC = 90.0
DEFAULT_WORKER_STABLE_RESET_SEC = 45.0
DEFAULT_CHAT_LEASE_TTL_SEC = 90.0
DEFAULT_CHAT_LEASE_HEARTBEAT_SEC = 20.0
DEFAULT_FILE_LOCK_WAIT_TIMEOUT_SEC = 1.0
DEFAULT_COMPLETED_MESSAGE_TTL_SEC = 180.0
DEFAULT_UI_MODE_TIMEOUT_SEC = 300.0
DEFAULT_NEW_TASK_SUMMARY_LINES = 50
DEFAULT_NEW_TASK_SUMMARY_MAX_CHARS = 12000
DEFAULT_RESUME_CHAT_SUMMARY_HOURS = 5
DEFAULT_RESUME_CHAT_SUMMARY_LINES = 30
DEFAULT_RESUME_CHAT_SUMMARY_MAX_CHARS = 12000
DEFAULT_TASK_GUIDE_TELEGRAM_CHUNK_CHARS = 500
DEFAULT_TASK_AGENTS_INSTRUCTIONS_MAX_CHARS = 12000
DEFAULT_TASK_SEARCH_LLM_ENABLED = True
DEFAULT_TASK_SEARCH_LLM_LIMIT = 5
DEFAULT_TASK_SEARCH_LLM_CANDIDATE_POOL_LIMIT = 80
DEFAULT_TASK_SEARCH_LLM_MIN_SCORE = 60
DEFAULT_TASK_SEARCH_LLM_TURN_TIMEOUT_SEC = 35.0
DEFAULT_TASK_SEARCH_LLM_REQUEST_TIMEOUT_SEC = 20.0

BUTTON_TASK_LIST_RECENT20 = "TASK 목록 보기(최근20)"
BUTTON_TASK_RESUME = "기존 TASK 이어하기"
BUTTON_TASK_NEW = "새 TASK 시작하기"
BUTTON_TASK_GUIDE_VIEW = "TASK 지침 보기"
BUTTON_BOT_RENAME = "봇이름 변경"
BUTTON_MENU_BACK = "메뉴로 돌아가기"

UI_MODE_IDLE = "idle"
UI_MODE_AWAITING_RESUME_QUERY = "awaiting_resume_query"
UI_MODE_AWAITING_RESUME_CHOICE = "awaiting_resume_choice"
UI_MODE_AWAITING_NEW_TASK_INPUT = "awaiting_new_task_input"
UI_MODE_AWAITING_TEMP_TASK_DECISION = "awaiting_temp_task_decision"
UI_MODE_AWAITING_TASK_GUIDE_EDIT = "awaiting_task_guide_edit"
UI_MODE_AWAITING_BOT_RENAME_ALIAS = "awaiting_bot_rename_alias"

CALLBACK_TASK_SELECT_PREFIX = "__cb__:task_select:"
INLINE_TASK_SELECT_CALLBACK_PREFIX = "task_select:"
LEGACY_TASK_THREAD_MAP_FILENAME = "legacy_task_thread_map.json"

INTERNAL_AGENT_TEXT_PATTERNS = (
    r"\bthread_[A-Za-z0-9._:-]+\b",
    r"\bmsg_\d+\b",
    r"\bINSTRUNCTION\.md\b",
    r"\bINSTRUCTIONS\.md\b",
    r"\bindex\.json\b",
    r"\btask_info\b",
    r"\btask_meta\b",
    r"\bcodex\b",
    r"\bapp-server\b",
    r"백그라운드",
    r"동기화",
    r"세션",
    r"메타",
    r"스크립트",
    r"명령어",
)

MCP_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
REWRITER_AGENTS_FILENAME = "AGENTS.md"
TASK_AGENTS_FILENAME = "AGENTS.md"
TASK_GUIDE_TRIGGER_TEXT = "task 지침"
TASK_GUIDE_EDIT_KEYWORDS = (
    "만들",
    "생성",
    "추가",
    "변경",
    "수정",
    "업데이트",
    "반영",
    "적용",
    "작성",
    "넣어",
)

FALLBACK_DAEMON_LOG_FILE = Path("/tmp/sonolbot-daemon-fallback.log")

__all__ = [name for name in globals() if not name.startswith("__")]
