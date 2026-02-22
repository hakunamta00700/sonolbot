#!/usr/bin/env python3
"""
Task memory helpers for Sonolbot task folders.

This module supports both legacy and current styles:
- legacy: tasks/msg_{message_id}/...
- current: tasks/thread_{thread_id}/...
- index key: task_id (thread_* preferred, msg_* legacy fallback)

Policy added by this skill:
- INSTRUNCTION.md is mandatory for each task
- read INSTRUNCTION.md first before working
- sync INSTRUNCTION.md on each change
- keep INSTRUNCTION.md compact
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency fallback
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


INDEX_FILENAME = "index.json"
TASK_INFO_FILENAME = "task_info.txt"
INSTRUNCTION_FILENAME = "INSTRUNCTION.md"  # Intentionally matches requested project policy spelling
RELATED_FILENAME = "related_tasks.json"
TASK_META_FILENAME = "task_meta.json"

DEFAULT_INSTRUNCTION_MAX_CHARS = 2600
DEFAULT_RELATED_LIMIT = 3
DEFAULT_RELATED_MIN_SCORE = 0.18
LOG_RETENTION_DAYS = 7
TASK_LOG_BASENAME = "tasks"
CODEX_SESSION_RECORD_ENV = "SONOLBOT_STORE_CODEX_SESSION"
CODEX_SESSION_META_FILE_ENV = "SONOLBOT_CODEX_SESSION_META_FILE"
DEFAULT_CODEX_SESSION_SCAN_WINDOW_SEC = 300
CODEX_CLI_VERSION_ENV = "SONOLBOT_CODEX_CLI_VERSION"
CODEX_MODEL_ENV = "SONOLBOT_CODEX_MODEL"
CODEX_REASONING_ENV = "SONOLBOT_CODEX_REASONING_EFFORT"
TITLE_STATE_PROVISIONAL = "provisional"
TITLE_STATE_FINAL = "final"
TASK_ID_THREAD_PREFIX = "thread_"
TASK_ID_MSG_PREFIX = "msg_"

OPS_NOISE_PATTERNS = (
    r"\back\b",
    r"dns",
    r"network",
    r"네트워크",
    r"송신\s*실패",
    r"재전송",
    r"재시도",
    r"전송\s*대기",
    r"telegram",
    r"텔레그램",
)

WORK_SIGNAL_PATTERNS = (
    r"완료",
    r"적용",
    r"반영",
    r"수정",
    r"추가",
    r"구현",
    r"정리",
    r"분석",
    r"작성",
    r"생성",
    r"업데이트",
)

WAITING_PATTERNS = (r"대기", r"보류", r"진행 중")
BLOCKED_PATTERNS = (r"차단", r"실패", r"오류", r"불가")
COMPLETION_PATTERNS = (r"완료", r"적용", r"반영", r"수정됨", r"전달", r"정리 완료")
SMALLTALK_PREFIX = ("안녕", "반가워", "고마워", "감사", "ㅎ", "ㅋㅋ", "하이")


def init_task_session(
    tasks_dir: str,
    instruction: str,
    message_id: int | None = None,
    thread_id: str | None = None,
    task_id: str | None = None,
    source_message_ids: list[int] | None = None,
    chat_id: int | None = None,
    timestamp: str | None = None,
    related_limit: int = DEFAULT_RELATED_LIMIT,
    min_related_score: float = DEFAULT_RELATED_MIN_SCORE,
    logs_dir: str | None = None,
) -> dict[str, Any]:
    """
    Create/initialize one task session folder and mandatory memory files.

    Returns:
        {
            "task_dir": str,
            "task_id": str,
            "thread_id": str,
            "message_id": int,
            "related_tasks": list[dict],
            "instrunction_path": str,
        }
    """
    root = Path(tasks_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    resolved_logs_dir = _resolve_logs_dir(root, logs_dir)
    msg_id = _safe_int(message_id, 0)
    normalized_task_id = _normalize_task_id(task_id=task_id, thread_id=thread_id, message_id=msg_id)
    if not normalized_task_id:
        raise ValueError("task_id/thread_id/message_id 중 하나는 필요합니다.")
    resolved_thread_id = _thread_id_from_task_id(normalized_task_id)
    normalized_source_ids = _normalize_source_message_ids(source_message_ids)
    if msg_id > 0:
        normalized_source_ids = _merge_source_message_ids(normalized_source_ids, [msg_id])

    task_dir = root / normalized_task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    codex_session = _current_codex_session_meta()
    if not resolved_thread_id and isinstance(codex_session, dict):
        resolved_thread_id = _sanitize_thread_id(codex_session.get("session_id"))
    if normalized_task_id.startswith(TASK_ID_THREAD_PREFIX) and not resolved_thread_id:
        resolved_thread_id = normalized_task_id[len(TASK_ID_THREAD_PREFIX) :]

    ts = _normalize_timestamp(timestamp)
    related = find_relevant_tasks(
        query=instruction,
        tasks_dir=str(root),
        limit=max(related_limit * 3, 10),
        min_score=min_related_score,
        exclude_task_ids={normalized_task_id},
        logs_dir=str(resolved_logs_dir),
    )[:related_limit]

    _write_related_file(task_dir, related)
    existing_entry = _load_index_entry(root / INDEX_FILENAME, normalized_task_id)
    display_fields = _compose_display_fields(
        instruction=instruction,
        result_summary="(작업 진행 중...)",
        latest_change="작업 세션 생성",
        previous_entry=existing_entry,
        note_count=1,
        event_ts=ts,
    )
    _upsert_index(
        root / INDEX_FILENAME,
        {
            "task_id": normalized_task_id,
            "thread_id": resolved_thread_id or "",
            "message_id": msg_id,
            "latest_message_id": _max_message_id(normalized_source_ids, fallback=msg_id),
            "source_message_ids": normalized_source_ids,
            "timestamp": ts,
            "instruction": instruction,
            "keywords": _extract_keywords(instruction),
            "result_summary": "(작업 진행 중...)",
            "files": [],
            "chat_id": chat_id,
            "task_dir": str(task_dir),
            "related_task_ids": _extract_related_task_ids(related),
            "codex_session": codex_session or {},
            **display_fields,
        },
    )

    _write_task_info(
        task_dir=task_dir,
        task_id=normalized_task_id,
        thread_id=resolved_thread_id,
        message_id=msg_id,
        source_message_ids=normalized_source_ids,
        chat_id=chat_id,
        message_timestamp=ts,
        instruction=instruction,
        result_text="(작업 진행 중...)",
        sent_files=[],
        related_tasks=related,
        codex_session=codex_session,
    )

    instrunction_path = sync_instrunction(
        task_dir=str(task_dir),
        instruction=instruction,
        related_tasks=related,
        codex_session=codex_session,
        latest_change="작업 세션 생성",
        max_chars=DEFAULT_INSTRUNCTION_MAX_CHARS,
        logs_dir=str(resolved_logs_dir),
    )

    _write_log(
        resolved_logs_dir,
        event="init_task_session",
        details={
            "task_id": normalized_task_id,
            "thread_id": resolved_thread_id or "",
            "message_id": msg_id,
            "task_dir": str(task_dir),
            "related_count": len(related),
        },
    )

    return {
        "task_dir": str(task_dir),
        "task_id": normalized_task_id,
        "thread_id": resolved_thread_id or "",
        "message_id": msg_id,
        "related_tasks": related,
        "instrunction_path": instrunction_path,
    }


def read_instrunction_first(task_dir: str, logs_dir: str | None = None) -> str:
    """
    Return INSTRUNCTION.md content.
    If missing, create a minimal file and return it.
    """
    task_path = Path(task_dir).resolve()
    task_path.mkdir(parents=True, exist_ok=True)
    resolved_logs_dir = _resolve_logs_dir(task_path.parent, logs_dir)
    p = task_path / INSTRUNCTION_FILENAME
    if not p.exists():
        sync_instrunction(
            task_dir=str(task_path),
            instruction="(지시사항 미입력)",
            related_tasks=[],
            latest_change="INSTRUNCTION.md 자동 생성",
            max_chars=DEFAULT_INSTRUNCTION_MAX_CHARS,
            logs_dir=str(resolved_logs_dir),
        )
    _write_log(resolved_logs_dir, event="read_instrunction_first", details={"task_dir": str(task_path)})
    return p.read_text(encoding="utf-8")


def record_task_change(
    tasks_dir: str,
    change_note: str,
    message_id: int | None = None,
    thread_id: str | None = None,
    task_id: str | None = None,
    source_message_ids: list[int] | None = None,
    result_summary: str | None = None,
    sent_files: list[str] | None = None,
    timestamp: str | None = None,
    logs_dir: str | None = None,
) -> dict[str, Any]:
    """
    Record one task change and synchronize:
    - INSTRUNCTION.md
    - task_info.txt
    - tasks/index.json
    """
    root = Path(tasks_dir).resolve()
    resolved_logs_dir = _resolve_logs_dir(root, logs_dir)
    msg_id = _safe_int(message_id, 0)
    normalized_task_id = _normalize_task_id(task_id=task_id, thread_id=thread_id, message_id=msg_id)
    if not normalized_task_id:
        raise ValueError("task_id/thread_id/message_id 중 하나는 필요합니다.")
    resolved_thread_id = _thread_id_from_task_id(normalized_task_id)
    normalized_source_ids = _normalize_source_message_ids(source_message_ids)
    if msg_id > 0:
        normalized_source_ids = _merge_source_message_ids(normalized_source_ids, [msg_id])
    task_dir = root / normalized_task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    codex_session = _current_codex_session_meta()
    if not resolved_thread_id and isinstance(codex_session, dict):
        resolved_thread_id = _sanitize_thread_id(codex_session.get("session_id"))
    if normalized_task_id.startswith(TASK_ID_THREAD_PREFIX) and not resolved_thread_id:
        resolved_thread_id = normalized_task_id[len(TASK_ID_THREAD_PREFIX) :]

    ts = _normalize_timestamp(timestamp)
    sent_files = sent_files or []
    previous_entry = _load_index_entry(root / INDEX_FILENAME, normalized_task_id)
    previous_source_ids = []
    if isinstance(previous_entry, dict):
        previous_source_ids = _normalize_source_message_ids(previous_entry.get("source_message_ids"))
    normalized_source_ids = _merge_source_message_ids(previous_source_ids, normalized_source_ids)
    instruction = _load_instruction_from_index(root / INDEX_FILENAME, normalized_task_id) or "(지시사항 미입력)"
    related = _load_related_file(task_dir)

    sync_instrunction(
        task_dir=str(task_dir),
        instruction=instruction,
        related_tasks=related,
        codex_session=codex_session,
        latest_change=change_note,
        max_chars=DEFAULT_INSTRUNCTION_MAX_CHARS,
        logs_dir=str(resolved_logs_dir),
    )

    result_text = result_summary or "(결과 업데이트 없음)"
    chat_id = _load_chat_id_from_index(root / INDEX_FILENAME, normalized_task_id)
    _write_task_info(
        task_dir=task_dir,
        task_id=normalized_task_id,
        thread_id=resolved_thread_id,
        message_id=msg_id,
        source_message_ids=normalized_source_ids,
        chat_id=chat_id,
        message_timestamp=ts,
        instruction=instruction,
        result_text=result_text,
        sent_files=sent_files,
        related_tasks=related,
        codex_session=codex_session,
    )

    latest_change_text = change_note or ""
    meta = _load_task_meta(task_dir)
    notes = meta.get("change_notes", [])
    note_count = len(notes) if isinstance(notes, list) else 0
    display_fields = _compose_display_fields(
        instruction=instruction,
        result_summary=result_text,
        latest_change=latest_change_text,
        previous_entry=previous_entry,
        note_count=note_count,
        event_ts=ts,
    )

    _upsert_index(
        root / INDEX_FILENAME,
        {
            "task_id": normalized_task_id,
            "thread_id": resolved_thread_id or "",
            "message_id": msg_id,
            "latest_message_id": _max_message_id(normalized_source_ids, fallback=msg_id),
            "source_message_ids": normalized_source_ids,
            "timestamp": ts,
            "instruction": instruction,
            "keywords": _extract_keywords(instruction),
            "result_summary": result_text[:300],
            "files": [os.path.basename(f) for f in sent_files],
            "chat_id": chat_id,
            "task_dir": str(task_dir),
            "related_task_ids": _extract_related_task_ids(related),
            "codex_session": codex_session or {},
            **display_fields,
        },
    )

    _write_log(
        resolved_logs_dir,
        event="record_task_change",
        details={
            "task_id": normalized_task_id,
            "thread_id": resolved_thread_id or "",
            "message_id": msg_id,
            "task_dir": str(task_dir),
            "sent_file_count": len(sent_files),
            "has_result_summary": bool(result_summary),
        },
    )

    return {
        "task_dir": str(task_dir),
        "task_id": normalized_task_id,
        "thread_id": resolved_thread_id or "",
        "message_id": msg_id,
        "result_summary": result_text,
        "sent_files": [os.path.basename(f) for f in sent_files],
    }


def sync_instrunction(
    task_dir: str,
    instruction: str | None = None,
    related_tasks: list[dict[str, Any]] | None = None,
    codex_session: dict[str, Any] | None = None,
    latest_change: str | None = None,
    max_chars: int = DEFAULT_INSTRUNCTION_MAX_CHARS,
    logs_dir: str | None = None,
) -> str:
    """
    Synchronize INSTRUNCTION.md with latest task state.
    Applies compaction if file grows over max_chars.
    """
    task_path = Path(task_dir).resolve()
    task_path.mkdir(parents=True, exist_ok=True)
    resolved_logs_dir = _resolve_logs_dir(task_path.parent, logs_dir)

    meta = _load_task_meta(task_path)
    if instruction is not None:
        meta["instruction"] = instruction.strip() or "(지시사항 미입력)"
    if related_tasks is not None:
        meta["related_tasks"] = related_tasks
    if codex_session is None:
        codex_session = _current_codex_session_meta()
    if codex_session:
        meta["codex_session"] = codex_session
    if latest_change:
        notes = meta.get("change_notes", [])
        notes.append(
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": latest_change.strip(),
            }
        )
        meta["change_notes"] = notes[-20:]
    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = _render_instrunction(task_path.name, meta)
    if len(content) > max_chars:
        content = _compact_instrunction(task_path.name, meta, max_chars=max_chars)

    (task_path / INSTRUNCTION_FILENAME).write_text(content, encoding="utf-8")
    _save_task_meta(task_path, meta)
    _write_log(
        resolved_logs_dir,
        event="sync_instrunction",
        details={
            "task_dir": str(task_path),
            "latest_change": latest_change or "",
            "content_len": len(content),
        },
    )
    return str(task_path / INSTRUNCTION_FILENAME)


def find_relevant_tasks(
    query: str,
    tasks_dir: str,
    limit: int = 5,
    min_score: float = DEFAULT_RELATED_MIN_SCORE,
    exclude_task_ids: set[str] | None = None,
    exclude_message_ids: set[int] | None = None,
    logs_dir: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find most relevant past tasks from index with low-token lexical scoring.
    """
    root = Path(tasks_dir).resolve()
    resolved_logs_dir = _resolve_logs_dir(root, logs_dir)
    index = _load_index(root / INDEX_FILENAME)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    exclude = exclude_message_ids or set()
    exclude_tasks = {_normalize_task_id(task_id=v) for v in (exclude_task_ids or set()) if _normalize_task_id(task_id=v)}
    scored: list[dict[str, Any]] = []
    now = datetime.now()

    for task in index.get("tasks", []):
        task_id = _entry_task_id(task)
        msg_id = _safe_int(task.get("latest_message_id"), _safe_int(task.get("message_id"), -1))
        if task_id and task_id in exclude_tasks:
            continue
        if msg_id in exclude:
            continue

        doc_text = " ".join(
            [
                str(task.get("instruction", "")),
                " ".join(task.get("keywords", []) or []),
                str(task.get("result_summary", "")),
                " ".join(task.get("files", []) or []),
            ]
        )
        doc_tokens = _tokenize(doc_text)
        if not doc_tokens:
            continue

        inter = query_tokens & doc_tokens
        if not inter:
            continue

        overlap_ratio = len(inter) / max(1, len(query_tokens))
        jaccard = len(inter) / max(1, len(query_tokens | doc_tokens))
        recency = _recency_score(task.get("timestamp"), now)

        score = (0.65 * overlap_ratio) + (0.25 * jaccard) + (0.10 * recency)
        if score < min_score:
            continue

        scored.append(
            {
                "task_id": task_id,
                "thread_id": _entry_thread_id(task),
                "message_id": msg_id,
                "score": round(score, 4),
                "instruction_excerpt": _short(task.get("instruction", ""), 140),
                "result_excerpt": _short(task.get("result_summary", ""), 140),
                "task_dir": task.get("task_dir"),
                "timestamp": task.get("timestamp"),
                "files": task.get("files", [])[:5],
            }
        )

    scored.sort(
        key=lambda x: (
            x["score"],
            _parse_epoch(x.get("timestamp")),
            x.get("task_id") or "",
        ),
        reverse=True,
    )
    result = scored[: max(0, int(limit))]
    _write_log(
        resolved_logs_dir,
        event="find_relevant_tasks",
        details={
            "query_excerpt": _short(query, 120),
            "limit": limit,
            "matched": len(result),
        },
    )
    return result


def build_compact_memory_packet(
    query: str,
    tasks_dir: str,
    limit: int = 3,
    max_chars: int = 1200,
    logs_dir: str | None = None,
) -> str:
    """
    Build low-token summary packet for prompt context.
    """
    matches = find_relevant_tasks(
        query=query,
        tasks_dir=tasks_dir,
        limit=limit,
        logs_dir=logs_dir,
    )
    if not matches:
        return "관련 TASK를 찾지 못했습니다."

    lines = ["[관련 TASK 요약]"]
    for i, item in enumerate(matches, 1):
        label = item.get("task_id") or (f"msg_{item['message_id']}" if _safe_int(item.get("message_id"), 0) > 0 else "unknown")
        lines.append(
            f"{i}. {label} (score={item['score']}) "
            f"- {item['instruction_excerpt']} | {item['result_excerpt']}"
        )

    text = "\n".join(lines)
    packet = _short(text, max_chars)
    resolved_logs_dir = _resolve_logs_dir(Path(tasks_dir).resolve(), logs_dir)
    _write_log(
        resolved_logs_dir,
        event="build_compact_memory_packet",
        details={"limit": limit, "packet_len": len(packet)},
    )
    return packet


def _write_task_info(
    task_dir: Path,
    task_id: str,
    thread_id: str | None,
    message_id: int,
    source_message_ids: list[int],
    chat_id: int | None,
    message_timestamp: str,
    instruction: str,
    result_text: str,
    sent_files: list[str],
    related_tasks: list[dict[str, Any]],
    codex_session: dict[str, Any] | None = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    related_ids = [str(r.get("task_id") or f"msg_{_safe_int(r.get('message_id'), 0)}").strip() for r in related_tasks]
    related_ids = [v for v in related_ids if v and v != "msg_0"]
    source_labels = [f"msg_{v}" for v in source_message_ids if int(v) > 0]

    lines = [
        f"[시간] {now}",
        f"[TASK_ID] {task_id}",
        f"[THREAD_ID] {thread_id or ''}",
        f"[출처] Telegram (chat_id: {chat_id})",
        f"[메시지날짜] {message_timestamp}",
        f"[지시] {instruction}",
        f"[결과] {result_text}",
    ]
    if message_id > 0:
        lines.append(f"[메시지ID] {message_id}")
    if source_labels:
        lines.append(f"[소스메시지] {', '.join(source_labels)}")
    if sent_files:
        lines.append(f"[보낸파일] {', '.join(os.path.basename(f) for f in sent_files)}")
    if related_ids:
        lines.append(f"[관련TASK] {', '.join(related_ids)}")
    if codex_session:
        run_id = str(codex_session.get("run_id") or "").strip()
        mode = str(codex_session.get("mode") or "").strip()
        started_at = str(codex_session.get("started_at") or "").strip()
        session_id = str(codex_session.get("session_id") or "").strip()
        codex_cli_version = str(codex_session.get("codex_cli_version") or "").strip()
        model = str(codex_session.get("model") or "").strip()
        reasoning_effort = str(codex_session.get("reasoning_effort") or "").strip()
        parts = []
        if run_id:
            parts.append(f"run_id={run_id}")
        if mode:
            parts.append(f"mode={mode}")
        if started_at:
            parts.append(f"started_at={started_at}")
        if session_id:
            parts.append(f"session_id={session_id}")
        if codex_cli_version:
            parts.append(f"codex_cli_version={codex_cli_version}")
        if model:
            parts.append(f"model={model}")
        if reasoning_effort:
            parts.append(f"reasoning_effort={reasoning_effort}")
        if parts:
            lines.append(f"[코덱스세션] {' | '.join(parts)}")
    lines.append(f"[지침파일] {INSTRUNCTION_FILENAME}")

    (task_dir / TASK_INFO_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_instrunction(task_folder_name: str, meta: dict[str, Any]) -> str:
    instruction = meta.get("instruction") or "(지시사항 미입력)"
    summary = _summarize_state(instruction, meta.get("change_notes", []), max_len=420)
    related = meta.get("related_tasks", [])
    codex_session = meta.get("codex_session") or {}
    notes = meta.get("change_notes", [])[-8:]

    lines = [
        f"# {INSTRUNCTION_FILENAME}",
        "",
        "- 이 파일을 항상 먼저 읽고 작업을 시작할 것.",
        f"- Task Folder: {task_folder_name}",
        f"- Last Updated: {meta.get('updated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
        "",
        "## Current Instruction",
        instruction,
        "",
        "## Related Task References",
    ]

    if related:
        for r in related[:5]:
            related_label = _normalize_task_id(
                task_id=r.get("task_id"),
                thread_id=r.get("thread_id"),
                message_id=_safe_int(r.get("message_id"), 0),
            )
            if not related_label:
                related_label = f"msg_{_safe_int(r.get('message_id'), 0)}"
            lines.append(
                f"- {related_label} (score={r['score']}): "
                f"{_short(r.get('instruction_excerpt', ''), 90)}"
            )
    else:
        lines.append("- (없음)")

    lines += ["", "## Codex Session (Optional)"]
    if isinstance(codex_session, dict) and codex_session:
        run_id = str(codex_session.get("run_id") or "").strip()
        mode = str(codex_session.get("mode") or "").strip()
        started_at = str(codex_session.get("started_at") or "").strip()
        session_id = str(codex_session.get("session_id") or "").strip()
        resume_target = str(codex_session.get("resume_target") or "").strip()
        codex_cli_version = str(codex_session.get("codex_cli_version") or "").strip()
        model = str(codex_session.get("model") or "").strip()
        reasoning_effort = str(codex_session.get("reasoning_effort") or "").strip()
        if run_id:
            lines.append(f"- run_id: {run_id}")
        if mode:
            lines.append(f"- mode: {mode}")
        if started_at:
            lines.append(f"- started_at: {started_at}")
        if session_id:
            lines.append(f"- session_id: {session_id}")
        if resume_target:
            lines.append(f"- resume_target: {resume_target}")
        if codex_cli_version:
            lines.append(f"- codex_cli_version: {codex_cli_version}")
        if model:
            lines.append(f"- model: {model}")
        if reasoning_effort:
            lines.append(f"- reasoning_effort: {reasoning_effort}")
    else:
        lines.append("- (기록 없음)")

    lines += ["", "## Compact Memory Summary", summary, "", "## Change Notes (Latest)"]
    if notes:
        for n in notes:
            lines.append(f"- [{n.get('timestamp')}] {_short(n.get('note', ''), 180)}")
    else:
        lines.append("- (기록 없음)")

    return "\n".join(lines).strip() + "\n"


def _compact_instrunction(task_folder_name: str, meta: dict[str, Any], max_chars: int) -> str:
    """
    Keep INSTRUNCTION.md short by reducing details in a deterministic way.
    """
    # Step 1: keep fewer notes
    notes = meta.get("change_notes", [])
    meta = dict(meta)
    meta["change_notes"] = notes[-4:]
    content = _render_instrunction(task_folder_name, meta)
    if len(content) <= max_chars:
        return content

    # Step 2: shorten instruction body
    meta["instruction"] = _short(meta.get("instruction", ""), 320)
    content = _render_instrunction(task_folder_name, meta)
    if len(content) <= max_chars:
        return content

    # Step 3: remove related details down to top 2
    meta["related_tasks"] = (meta.get("related_tasks") or [])[:2]
    content = _render_instrunction(task_folder_name, meta)
    if len(content) <= max_chars:
        return content

    # Step 4: hard trim as last resort
    return _short(content, max_chars - 1) + "\n"


def _load_task_meta(task_dir: Path) -> dict[str, Any]:
    p = task_dir / TASK_META_FILENAME
    if not p.exists():
        return {
            "instruction": "(지시사항 미입력)",
            "related_tasks": [],
            "codex_session": {},
            "change_notes": [],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {
            "instruction": "(지시사항 미입력)",
            "related_tasks": [],
            "codex_session": {},
            "change_notes": [],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def _save_task_meta(task_dir: Path, meta: dict[str, Any]) -> None:
    (task_dir / TASK_META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_codex_session_record_enabled() -> bool:
    raw = (os.getenv(CODEX_SESSION_RECORD_ENV, "1") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _current_codex_session_meta() -> dict[str, Any] | None:
    if not _is_codex_session_record_enabled():
        return None

    run_id = (os.getenv("SONOLBOT_CODEX_RUN_ID", "") or "").strip()
    mode = (os.getenv("SONOLBOT_CODEX_MODE", "") or "").strip()
    started_at = (os.getenv("SONOLBOT_CODEX_STARTED_AT", "") or "").strip()
    resume_target = (os.getenv("SONOLBOT_CODEX_RESUME_TARGET", "") or "").strip()
    session_id = (os.getenv("SONOLBOT_CODEX_SESSION_ID", "") or "").strip()
    codex_cli_version = (os.getenv(CODEX_CLI_VERSION_ENV, "") or "").strip()
    model = (os.getenv(CODEX_MODEL_ENV, "") or "").strip()
    reasoning_effort = (os.getenv(CODEX_REASONING_ENV, "") or "").strip()
    if not session_id:
        session_id = _session_id_from_meta_file(run_id)
    if not session_id and started_at:
        session_id = _resolve_session_id_from_sessions(started_at)
    if session_id:
        _upsert_session_id_to_meta_file(run_id, started_at, session_id)

    if not any([run_id, mode, started_at, resume_target, session_id, codex_cli_version, model, reasoning_effort]):
        return None

    data: dict[str, Any] = {}
    if run_id:
        data["run_id"] = run_id
    if mode:
        data["mode"] = mode
    if started_at:
        data["started_at"] = started_at
    if resume_target:
        data["resume_target"] = resume_target
    if session_id:
        data["session_id"] = session_id
    if codex_cli_version:
        data["codex_cli_version"] = codex_cli_version
    if model:
        data["model"] = model
    if reasoning_effort:
        data["reasoning_effort"] = reasoning_effort
    return data


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except ValueError:
        return max(minimum, default)


def _session_id_from_meta_file(run_id: str) -> str:
    meta_path_raw = (os.getenv(CODEX_SESSION_META_FILE_ENV, "") or "").strip()
    if not meta_path_raw:
        return ""
    p = Path(meta_path_raw).expanduser()
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    file_run_id = str(data.get("run_id") or "").strip()
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return ""
    if run_id and file_run_id and run_id != file_run_id:
        return ""
    return session_id


def _upsert_session_id_to_meta_file(run_id: str, started_at: str, session_id: str) -> None:
    if not session_id:
        return
    meta_path_raw = (os.getenv(CODEX_SESSION_META_FILE_ENV, "") or "").strip()
    if not meta_path_raw:
        return
    p = Path(meta_path_raw).expanduser()
    try:
        data: dict[str, Any] = {}
        if p.exists():
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        file_run_id = str(data.get("run_id") or "").strip()
        if run_id and file_run_id and run_id != file_run_id:
            return
        data["session_id"] = session_id
        if run_id and not file_run_id:
            data["run_id"] = run_id
        if started_at and not str(data.get("started_at") or "").strip():
            data["started_at"] = started_at
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _resolve_session_id_from_sessions(started_at: str) -> str:
    try:
        started_dt = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    started_epoch = started_dt.timestamp()
    scan_window_sec = _env_int("SONOLBOT_CODEX_SESSION_SCAN_WINDOW_SEC", DEFAULT_CODEX_SESSION_SCAN_WINDOW_SEC, minimum=60)
    lower_bound = started_epoch - 20
    upper_bound = started_epoch + scan_window_sec
    candidates: list[tuple[int, float, str]] = []

    for session_root in _candidate_codex_session_roots():
        for day_dir in _candidate_session_day_dirs(session_root, started_dt):
            for path in day_dir.glob("*.jsonl"):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime < lower_bound or mtime > upper_bound:
                    continue
                session_id = _extract_session_id_from_jsonl(path)
                if not session_id:
                    continue
                starts_after = 0 if mtime >= started_epoch else 1
                delta = abs(mtime - started_epoch)
                candidates.append((starts_after, delta, session_id))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _candidate_codex_session_roots() -> list[Path]:
    homes: list[Path] = [Path.home()]
    env_home = (os.getenv("HOME", "") or "").strip()
    if env_home:
        homes.append(Path(env_home).expanduser())

    roots: list[Path] = []
    seen: set[str] = set()
    for home in homes:
        key = str(home.resolve()) if home.exists() else str(home)
        if key in seen:
            continue
        seen.add(key)
        candidate = (home / ".codex" / "sessions").resolve()
        if candidate.exists() and candidate.is_dir():
            roots.append(candidate)
    return roots


def _candidate_session_day_dirs(session_root: Path, started_dt: datetime) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for day_offset in (-1, 0, 1):
        day = started_dt + timedelta(days=day_offset)
        p = session_root / day.strftime("%Y") / day.strftime("%m") / day.strftime("%d")
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.exists() and p.is_dir():
            out.append(p)
    return out


def _extract_session_id_from_jsonl(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "session_meta":
                    continue
                payload = item.get("payload")
                if isinstance(payload, dict):
                    session_id = str(payload.get("id") or "").strip()
                    if session_id:
                        return session_id
    except OSError:
        return ""

    match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        path.name,
    )
    if match:
        return match.group(1)
    return ""


def _write_related_file(task_dir: Path, related: list[dict[str, Any]]) -> None:
    (task_dir / RELATED_FILENAME).write_text(
        json.dumps({"related_tasks": related}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_related_file(task_dir: Path) -> list[dict[str, Any]]:
    p = task_dir / RELATED_FILENAME
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("related_tasks", [])
    except Exception:
        return []


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _save_index(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_index(index_path: Path, entry: dict[str, Any]) -> None:
    idx = _load_index(index_path)
    tasks = idx.get("tasks", [])
    task_id = _normalize_task_id(
        task_id=entry.get("task_id"),
        thread_id=entry.get("thread_id"),
        message_id=_safe_int(entry.get("message_id"), 0),
    )
    if not task_id:
        raise ValueError("index entry에 task_id/thread_id/message_id가 필요합니다.")
    entry["task_id"] = task_id
    if not str(entry.get("task_dir") or "").strip():
        entry["task_dir"] = str(index_path.parent / task_id)
    if not str(entry.get("thread_id") or "").strip():
        entry["thread_id"] = _thread_id_from_task_id(task_id)
    entry["source_message_ids"] = _normalize_source_message_ids(entry.get("source_message_ids"))
    latest_id = _safe_int(entry.get("latest_message_id"), 0)
    fallback_msg = _safe_int(entry.get("message_id"), 0)
    entry["latest_message_id"] = _max_message_id(entry["source_message_ids"], fallback=(latest_id or fallback_msg))
    found = False

    for t in tasks:
        if _entry_task_id(t) == task_id:
            t.update(entry)
            found = True
            break
    if not found:
        tasks.append(entry)

    tasks.sort(key=_task_sort_key, reverse=True)
    idx["tasks"] = tasks
    _save_index(index_path, idx)


def _load_instruction_from_index(index_path: Path, task_id: str) -> str | None:
    idx = _load_index(index_path)
    for t in idx.get("tasks", []):
        if _entry_task_id(t) == _normalize_task_id(task_id=task_id):
            text = str(t.get("instruction", "")).strip()
            return text if text else None
    return None


def _load_chat_id_from_index(index_path: Path, task_id: str) -> int | None:
    idx = _load_index(index_path)
    for t in idx.get("tasks", []):
        if _entry_task_id(t) == _normalize_task_id(task_id=task_id):
            chat_id = t.get("chat_id")
            if isinstance(chat_id, int):
                return chat_id
            if isinstance(chat_id, str) and chat_id.isdigit():
                return int(chat_id)
    return None


def _load_index_entry(index_path: Path, task_id: str) -> dict[str, Any] | None:
    idx = _load_index(index_path)
    for task in idx.get("tasks", []):
        if _entry_task_id(task) == _normalize_task_id(task_id=task_id):
            if isinstance(task, dict):
                return dict(task)
            return None
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _sanitize_thread_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(TASK_ID_THREAD_PREFIX):
        text = text[len(TASK_ID_THREAD_PREFIX) :]
    return text.strip()


def _thread_id_from_task_id(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    if normalized.startswith(TASK_ID_THREAD_PREFIX):
        return normalized[len(TASK_ID_THREAD_PREFIX) :]
    return ""


def _normalize_task_id(
    task_id: Any | None = None,
    thread_id: Any | None = None,
    message_id: int | None = None,
) -> str:
    raw_task_id = str(task_id or "").strip()
    if raw_task_id:
        if raw_task_id.startswith(TASK_ID_THREAD_PREFIX):
            thread = _sanitize_thread_id(raw_task_id)
            return f"{TASK_ID_THREAD_PREFIX}{thread}" if thread else ""
        if raw_task_id.startswith(TASK_ID_MSG_PREFIX):
            msg_id = _safe_int(raw_task_id[len(TASK_ID_MSG_PREFIX) :], 0)
            return f"{TASK_ID_MSG_PREFIX}{msg_id}" if msg_id > 0 else ""
        if raw_task_id.isdigit():
            msg_id = _safe_int(raw_task_id, 0)
            return f"{TASK_ID_MSG_PREFIX}{msg_id}" if msg_id > 0 else ""
        # bare uuid-like id는 thread id로 취급
        thread = _sanitize_thread_id(raw_task_id)
        return f"{TASK_ID_THREAD_PREFIX}{thread}" if thread else ""

    normalized_thread = _sanitize_thread_id(thread_id)
    if normalized_thread:
        return f"{TASK_ID_THREAD_PREFIX}{normalized_thread}"
    msg_id = _safe_int(message_id, 0)
    if msg_id > 0:
        return f"{TASK_ID_MSG_PREFIX}{msg_id}"
    return ""


def _entry_task_id(entry: dict[str, Any]) -> str:
    explicit = _normalize_task_id(
        task_id=entry.get("task_id"),
        thread_id=entry.get("thread_id"),
    )
    if explicit:
        return explicit

    task_dir = str(entry.get("task_dir") or "").strip()
    if task_dir:
        name = Path(task_dir).name
        from_dir = _normalize_task_id(task_id=name)
        if from_dir:
            return from_dir

    message_id = _safe_int(entry.get("latest_message_id"), _safe_int(entry.get("message_id"), 0))
    if message_id > 0:
        return _normalize_task_id(message_id=message_id)
    return ""


def _entry_thread_id(entry: dict[str, Any]) -> str:
    value = _sanitize_thread_id(entry.get("thread_id"))
    if value:
        return value
    task_id = _entry_task_id(entry)
    value = _thread_id_from_task_id(task_id)
    if value:
        return value
    return ""


def _normalize_source_message_ids(values: Any) -> list[int]:
    out: list[int] = []
    if not isinstance(values, list):
        return out
    for raw in values:
        msg_id = _safe_int(raw, 0)
        if msg_id > 0:
            out.append(msg_id)
    return sorted(set(out))


def _merge_source_message_ids(base: list[int], extra: list[int]) -> list[int]:
    merged = sorted({int(v) for v in (base or []) + (extra or []) if int(v) > 0})
    if len(merged) > 200:
        return merged[-200:]
    return merged


def _max_message_id(message_ids: list[int], fallback: int = 0) -> int:
    if message_ids:
        return max(int(v) for v in message_ids if int(v) > 0)
    return _safe_int(fallback, 0)


def _extract_related_task_ids(related: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in related:
        if not isinstance(item, dict):
            continue
        task_id = _normalize_task_id(
            task_id=item.get("task_id"),
            thread_id=item.get("thread_id"),
            message_id=_safe_int(item.get("message_id"), 0),
        )
        if task_id:
            ids.append(task_id)
    return ids


def _parse_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def _task_sort_key(entry: dict[str, Any]) -> tuple[float, int, str]:
    ts = _parse_epoch(entry.get("timestamp"))
    latest_message_id = _safe_int(entry.get("latest_message_id"), _safe_int(entry.get("message_id"), 0))
    return (ts, latest_message_id, _entry_task_id(entry))


def _contains_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return True
    return False


def _compact_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_latest_change_text(latest_change: str) -> str:
    value = _compact_space(latest_change)
    if not value:
        return ""
    if "|" not in value:
        return value
    return _compact_space(value.split("|", 1)[1])


def _normalize_instruction_for_title(instruction: str) -> str:
    value = _compact_space(instruction)
    if not value:
        return ""
    value = re.sub(r"^/\w+\s*", "", value).strip()
    value = re.sub(r"^(안녕(?:하세요)?|반가워요?|고마워요?|감사(?:합니다)?)[\s,!.]*", "", value).strip()
    return value


def _title_from_text(text: str, max_len: int = 30) -> str:
    value = _compact_space(text)
    if not value:
        return "새 작업"
    value = re.split(r"[.!?\n]", value, maxsplit=1)[0].strip(" -:|")
    if not value:
        return "새 작업"
    if len(value) <= max_len:
        return value
    return _short(value, max_len)


def _is_smalltalk_text(text: str) -> bool:
    value = _compact_space(text)
    if not value:
        return True
    if len(value) > 18:
        return False
    return value.startswith(SMALLTALK_PREFIX)


def _is_ops_noise_text(text: str) -> bool:
    return _contains_pattern(text, OPS_NOISE_PATTERNS)


def _has_work_signal(text: str) -> bool:
    if _is_ops_noise_text(text):
        return False
    return _contains_pattern(text, WORK_SIGNAL_PATTERNS)


def _has_completion_signal(text: str) -> bool:
    if _is_ops_noise_text(text):
        return False
    return _contains_pattern(text, COMPLETION_PATTERNS)


def _derive_work_status(result_summary: str, latest_change: str) -> str:
    text = f"{result_summary} {latest_change}".strip()
    if not text:
        return "in_progress"
    if _contains_pattern(text, WAITING_PATTERNS):
        return "waiting"
    if _contains_pattern(text, BLOCKED_PATTERNS) and not _is_ops_noise_text(text):
        return "blocked"
    if _has_work_signal(text):
        return "updated"
    if "작업 진행 중" in text:
        return "in_progress"
    return "updated"


def _derive_ops_status(result_summary: str, latest_change: str) -> str:
    text = f"{result_summary} {latest_change}".strip()
    if not text:
        return "unknown"
    if _contains_pattern(text, (r"dns", r"network", r"네트워크")):
        return "network_error"
    if _is_ops_noise_text(text):
        return "send_retry"
    return "ok"


def _derive_display_subtitle(instruction: str, result_summary: str, latest_change: str) -> str:
    candidates = [
        _compact_space(result_summary),
        _extract_latest_change_text(latest_change),
        _compact_space(instruction),
    ]
    for idx, value in enumerate(candidates):
        if not value:
            continue
        # result/latest change는 운영 노이즈를 우선 제외하고 업무 문장만 노출한다.
        if idx < 2 and _is_ops_noise_text(value):
            continue
        return _short(value, 60)
    fallback = _compact_space(instruction) or "요약 정보 없음"
    return _short(fallback, 60)


def _title_quality_score(title: str) -> int:
    value = _compact_space(title)
    if not value:
        return 0
    score = min(len(value), 30)
    if _is_smalltalk_text(value):
        score -= 15
    if value in ("새 작업", "일반 문의"):
        score -= 10
    return score


def _pick_better_title(current: str, candidate: str) -> str:
    cur = _compact_space(current)
    cand = _compact_space(candidate)
    if not cur:
        return cand or cur
    if not cand:
        return cur
    if _title_quality_score(cand) > _title_quality_score(cur):
        return cand
    return cur


def _compose_display_fields(
    instruction: str,
    result_summary: str,
    latest_change: str,
    previous_entry: dict[str, Any] | None,
    note_count: int,
    event_ts: str,
) -> dict[str, Any]:
    previous = previous_entry or {}
    prev_title = _compact_space(str(previous.get("display_title") or ""))
    prev_state_raw = str(previous.get("title_state") or "").strip().lower()
    prev_state = prev_state_raw if prev_state_raw in (TITLE_STATE_PROVISIONAL, TITLE_STATE_FINAL) else TITLE_STATE_PROVISIONAL
    prev_updated_at = _compact_space(str(previous.get("title_updated_at") or ""))

    normalized_instruction = _normalize_instruction_for_title(instruction)
    candidate_title = _title_from_text(normalized_instruction, max_len=30)
    if _is_smalltalk_text(candidate_title):
        candidate_title = "일반 문의"

    subtitle = _derive_display_subtitle(instruction, result_summary, latest_change)
    if candidate_title in ("새 작업", "일반 문의") and subtitle and not _is_ops_noise_text(subtitle):
        candidate_title = _title_from_text(subtitle, max_len=30)

    if prev_state == TITLE_STATE_FINAL and prev_title:
        display_title = prev_title
    elif prev_title:
        display_title = _pick_better_title(prev_title, candidate_title)
    else:
        display_title = candidate_title

    summarize_text = f"{result_summary} {latest_change}".strip()
    should_finalize = (
        prev_state == TITLE_STATE_FINAL
        or _has_completion_signal(summarize_text)
        or (note_count >= 2 and _has_work_signal(summarize_text))
        or note_count >= 4
    )
    title_state = TITLE_STATE_FINAL if should_finalize else TITLE_STATE_PROVISIONAL
    if title_state == TITLE_STATE_FINAL and prev_state == TITLE_STATE_FINAL and prev_title:
        display_title = prev_title

    work_status = _derive_work_status(result_summary, latest_change)
    ops_status = _derive_ops_status(result_summary, latest_change)

    changed = display_title != prev_title or title_state != prev_state
    title_updated_at = event_ts if changed or not prev_updated_at else prev_updated_at

    return {
        "display_title": display_title or "새 작업",
        "display_subtitle": subtitle,
        "title_state": title_state,
        "title_updated_at": title_updated_at,
        "work_status": work_status,
        "ops_status": ops_status,
    }


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9가-힣_]+", text or "")
    out = []
    seen = set()
    for tok in tokens:
        if len(tok) < 2:
            continue
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tok)
        if len(out) >= 12:
            break
    return out


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9가-힣_]+", text or "")
    return {t.lower() for t in tokens if len(t) >= 2}


def _short(text: str, limit: int) -> str:
    s = (text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 3)] + "..."


def _normalize_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(timestamp, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _recency_score(timestamp: Any, now: datetime) -> float:
    if not timestamp:
        return 0.0
    try:
        dt = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0.0
    days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return 1.0 / (1.0 + (days / 7.0))


def _summarize_state(instruction: str, notes: list[dict[str, Any]], max_len: int) -> str:
    base = _short(instruction, max_len // 2)
    if not notes:
        return f"현재 핵심 지시: {base}"
    latest = _short(notes[-1].get("note", ""), max_len // 2)
    s = f"핵심 지시: {base} | 최신 변경: {latest}"
    return _short(s, max_len)


def _resolve_logs_dir(tasks_root: Path, logs_dir: str | None) -> Path:
    if logs_dir:
        p = Path(logs_dir).resolve()
    else:
        p = (tasks_root.parent / "logs").resolve()
    p.mkdir(parents=True, exist_ok=True)
    _cleanup_old_logs(p)
    return p


def _write_log(logs_dir: Path, event: str, details: dict[str, Any]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_logs(logs_dir)
    p = logs_dir / f"{TASK_LOG_BASENAME}-{datetime.now().strftime('%Y-%m-%d')}.log"
    rec = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "details": details,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _cleanup_old_logs(logs_dir: Path) -> None:
    cutoff = datetime.now().date() - timedelta(days=LOG_RETENTION_DAYS - 1)
    for log_file in logs_dir.glob(f"{TASK_LOG_BASENAME}-*.log"):
        m = re.match(rf"{TASK_LOG_BASENAME}-(\d{{4}}-\d{{2}}-\d{{2}})$", log_file.stem)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            try:
                log_file.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    # Minimal smoke test for local execution.
    demo_root = Path("/tmp/sonolnot_tasks_demo")
    session = init_task_session(
        tasks_dir=str(demo_root),
        task_id="thread_demo-1",
        thread_id="demo-1",
        message_id=1,
        source_message_ids=[1],
        instruction="카페 랜딩페이지 시안 개선",
        chat_id=123456,
        timestamp="2026-02-12 10:00:00",
    )
    print("created:", session["task_dir"])
    print(read_instrunction_first(session["task_dir"]).splitlines()[0])
    change = record_task_change(
        tasks_dir=str(demo_root),
        task_id="thread_demo-1",
        thread_id="demo-1",
        message_id=1,
        source_message_ids=[1],
        change_note="색상 테마 변경",
        result_summary="테마 색상 변경 완료",
        sent_files=["index.html"],
    )
    print("updated:", change["result_summary"])
