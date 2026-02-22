---
name: sonolbot-telegram
description: Telegram message I/O toolkit for Sonolbot. Use when implementing or refactoring skill-based Telegram integration (via skill_bridge/quick_check/daemon) with strict allowed-user filtering, rich attachment intake, optional 24h context function, raw text+file sending, and 7-day log retention.
---

# Sonolbot Telegram

## Overview

Implement Telegram receive/send behavior with required user filtering, rich attachment intake, and predictable logging. Keep 24-hour context generation separate from receive flow and call it only when needed.

## Current Runtime Wiring

- Runtime variables are assembled by `skill_bridge.py` via `build_telegram_runtime()`.
- Polling and pending detection are executed by `quick_check.py`.
- Continuous execution is handled by `mybot_autoexecutor.sh` (foreground daemon).

## When To Use

- Use this skill for all Telegram receive/send and message-store behavior in this repo.
- Use this skill when you need allowed-user filtering, attachment intake, raw text/file send, or Telegram log retention.

## Runtime Variables (Provided By AI)

Pass runtime values as a dict to `build_runtime_vars(...)` in `scripts/telegram_io.py`.

| Variable | Required | Type | Purpose |
|---|---|---|---|
| `telegram_bot_token` | Yes | `str` | Bot token for Telegram API. |
| `telegram_allowed_users` | Yes | `list[int]` or `str` | Allowed Telegram user IDs. Receive flow always filters by this list. |
| `telegram_user_id` | No | `int` | Primary operator user ID (metadata or default target). |
| `telegram_include_24h_context` | No | `bool` | Flag for optional context usage in your app layer. |
| `work_dir` | No | `str` | Working directory for `logs/`, `tasks/`, and message store files. Default: current directory. |
| `tasks_dir` | No | `str` | Override task download base dir. Default: `{work_dir}/tasks`. |
| `logs_dir` | No | `str` | Override telegram log dir. Default: `{work_dir}/logs`. |
| `api_timeout_sec` | No | `float` | API timeout. Default: `20.0`. |
| `polling_timeout_sec` | No | `int` | Long-poll timeout for receive. Default: `5`. |
| `message_retention_days` | No | `int` | Message-store retention days. Old entries are pruned while `last_update_id` is preserved. Default: `7`. |

## Required Rules

- Enforce allowed-user filtering in receive path.
- Support intake for text, photo, document, video, audio, voice, and location.
- Keep 24h context generation out of receive path.
- Send text without rewriting or formatting it.
- 사용자-facing 답변 문안은 텔레그램 HTML 파싱 기준을 우선한다.
  - 강조가 필요하면 `<b>`, `<code>`만 최소 사용한다.
  - Markdown 문법(`*`, `_`, `#`, ```) 의존 포맷은 피한다.
- 사용자가 봇 이름 변경을 요청하면, 데몬의 안전 경로(`setMyName` -> `getMyName` 검증 -> 설정 저장)로만 처리한다.
  - `.control_panel_telegram_bots.json` 파일을 정규식/치환(`sed`, `perl`, 수동 문자열 붙이기)으로 직접 수정하지 않는다.
- 문자열 줄바꿈 규칙:
  - 코드 문자열에서는 실제 줄바꿈 `\n`을 사용한다.
  - 문자열에 리터럴 `\\n`(백슬래시+n 문자)로 작성하지 않는다.
- In unstable DNS/network environments, reduce send count:
  - Use one combined message for `ACK + progress` via `send_ack_and_progress(...)`.
  - Do not send a separate completion notification; include completion in final answer body via `send_final_answer(..., include_completion_in_body=True)`.
- On send failure, do not immediately send extra "failure cause" text:
  - keep local logs/state only
  - retry in next normal cycle
- For `agent_message`-based intermediate sends, prioritize short status text with internal system/policy wording removed.
- Keep the final answer (`last_agent_message`) as the complete user-facing response body.
- Handle file sending separately and safely.
- Log every receive/send event.
- Store logs under `logs/` in current working directory.
- Create `logs/` automatically if missing.
- Keep only last 7 days of logs and delete older logs automatically.
- Keep only recent messages in `telegram_messages.json` (default 7 days) by pruning old entries without resetting `last_update_id`.

## Workflow

1. Build runtime vars:

```python
from scripts.telegram_io import build_runtime_vars

runtime = build_runtime_vars({
    "telegram_bot_token": "...",
    "telegram_allowed_users": [123456789],
    "telegram_user_id": 123456789,
    "telegram_include_24h_context": False,
    "work_dir": ".",
})
```

2. Receive one poll and store:

```python
from scripts.telegram_io import receive_once, append_messages_to_store

new_messages, new_last_update_id = receive_once(runtime, last_update_id=0)
append_messages_to_store("telegram_messages.json", new_messages, new_last_update_id)
```

3. Build 24h context only when needed:

```python
from scripts.telegram_io import load_message_store, build_24h_context

store = load_message_store("telegram_messages.json")
context_text = build_24h_context(store["messages"], current_message_id=12345)
```

4. Send with resilient policy (recommended), or raw send when needed:

```python
from scripts.telegram_io import (
    send_ack_and_progress,
    send_final_answer,
    send_text_retry,
    send_files_raw,
)

send_ack_and_progress(
    runtime,
    chat_id=123456789,
    message_id=123,
    stage="요청 분석 중",
    summary="질문 범위를 확인하고 있습니다.",
)
send_final_answer(
    runtime,
    chat_id=123456789,
    message_id=123,
    answer_text="요청하신 내용 처리를 완료했습니다.",
    include_completion_in_body=True,
)
# raw send가 꼭 필요하면 message-level retry wrapper를 사용
send_text_retry(runtime, chat_id=123456789, text="원문 그대로 전송")
send_files_raw(runtime, chat_id=123456789, text="파일 전송", file_paths=["result.pdf"])
```

Anti-pattern (금지):
- `if not ans_ok: send_text(chat_id, cause)` 같은 실패 직후 추가 전송
- `ACK`, `진행상황`, `완료 알림`을 모두 분리 전송해 API 호출 수를 과도하게 늘리는 패턴

## I/O Schema (Short)

`receive_once(...)` output item:
```json
{
  "message_id": 123,
  "type": "user",
  "chat_id": 111,
  "text": "hello",
  "files": [{"type": "photo", "path": "...", "size": 12345}],
  "location": {"latitude": 37.56, "longitude": 126.97, "accuracy": 15.5},
  "timestamp": "2026-02-12 10:00:00",
  "processed": false
}
```

`send_text_raw(...)` / `send_file_raw(...)` / `send_files_raw(...)` return:
```json
true
```

`build_24h_context(...)` return:
```json
"context string"
```

## Resources

- `scripts/telegram_io.py`: Telegram I/O module with receive, send, 24h context builder, and log retention.
