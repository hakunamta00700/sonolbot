---
name: sonolbot-tasks
description: Tasks memory system for Sonolbot. Use when defining or refactoring skill-based task persistence under tasks/chat_{chat_id}/thread_* folders (legacy msg_* read compatibility), low-token relevant-task retrieval, related-task references, and mandatory INSTRUNCTION.md read-first/sync/compaction rules.
---

# Sonolbot Tasks

## Overview

Standardize task storage under `tasks/` as durable memory. Enforce mandatory `INSTRUNCTION.md` per task, keep it synchronized with task changes, and compact it when it grows too long.

## Current Runtime Wiring

- This skill is invoked through `skill_bridge.py` (`get_task_skill()`).
- New Telegram-driven work started by the daemon prompt must create/manage task sessions using this skill.
- Task logs are written under configurable `logs_dir` (default project `logs/`).

## When To Use

- Use this skill whenever creating/updating/searching task memory in `tasks/`.
- Use this skill when you must enforce `INSTRUNCTION.md` first-read and sync rules.

## Current System Compatibility

This skill is built to match the current project format:
- `tasks/index.json` with keys like `task_id`, `thread_id`, `latest_message_id`, `source_message_ids`, `instruction`, `result_summary`, `task_dir`, `timestamp`, `chat_id`
- per-task folder `tasks/chat_{chat_id}/thread_{thread_id}/` (or `tasks/thread_{thread_id}/` when chat partition is off)
- legacy `tasks/chat_{chat_id}/msg_{message_id}/` is read-compatible
- memory file `task_info.txt`

## Required Rules

- Every task uses its own folder: `tasks/chat_{chat_id}/thread_{thread_id}/` (legacy `msg_*` read-only compatibility).
- Every task must have `INSTRUNCTION.md`.
- Worker must read `INSTRUNCTION.md` first before doing any task work.
- On task change, `INSTRUNCTION.md` must be synchronized immediately.
- `INSTRUNCTION.md` must stay short; compact/summarize when oversized.
- If related tasks exist, save reference metadata in a deterministic way.
- Task logs should be written to configurable `logs_dir` (default: project `logs/`).
- Task-memory rules are internal execution rules; do not expose rule names or filenames in intermediate user notifications.
- If intermediate progress is needed, provide a short, user-friendly work-status summary only.

## Related Task Selection Rule

Use lexical relevance from `tasks/index.json` with:
1. token overlap (instruction/query/keywords/result_summary)
2. lightweight recency boost
3. score threshold filter
4. top-N keep

Persist related-task references in:
- `tasks/chat_{chat_id}/thread_{thread_id}/related_tasks.json` (legacy `msg_*` fallback)
- `INSTRUNCTION.md` section `Related Task References`

## Quick Usage

```python
from scripts.task_memory import (
    init_task_session,
    build_compact_memory_packet,
    read_instrunction_first,
    record_task_change,
)

# 1) create task session + INSTRUNCTION.md + related refs
session = init_task_session(
    tasks_dir="tasks",
    task_id="thread_019c615b-1215-79c3-9ca7-bff6633cf4e0",
    thread_id="019c615b-1215-79c3-9ca7-bff6633cf4e0",
    message_id=501,
    source_message_ids=[501],
    instruction="카페 랜딩페이지 수정",
    chat_id=123456789,
    timestamp="2026-02-12 10:30:00",
    logs_dir="logs",
)

# 2) read mandatory guideline first
guideline = read_instrunction_first(session["task_dir"])

# 3) token-light memory retrieval for current query
packet = build_compact_memory_packet(
    query="카페 랜딩페이지 다크모드",
    tasks_dir="tasks",
    limit=3,
    max_chars=1200,
    logs_dir="logs",
)

# 4) sync task memory on change
record_task_change(
    tasks_dir="tasks",
    task_id="thread_019c615b-1215-79c3-9ca7-bff6633cf4e0",
    thread_id="019c615b-1215-79c3-9ca7-bff6633cf4e0",
    message_id=501,
    source_message_ids=[501],
    change_note="다크모드 토글 추가",
    result_summary="다크모드 적용 완료",
    sent_files=["index.html", "styles.css"],
    logs_dir="logs",
)
```

## Resources

- `scripts/task_memory.py`: task session creation, relevance search, reference persistence, INSTRUNCTION.md sync/compaction.
