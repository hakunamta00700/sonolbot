"""Pure utility helpers for daemon service logic."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from sonolbot.core.daemon.constants import DEFAULT_TASK_GUIDE_TELEGRAM_CHUNK_CHARS


def _coerce_float(raw: str, default: float, minimum: float) -> float:
    raw = raw.strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, float(raw))
    except ValueError:
        return max(minimum, default)


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except ValueError:
        return max(minimum, default)


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    return _coerce_float(os.getenv(name, ""), default, minimum)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def build_session_thread_payload(mapping: dict[int, str]) -> dict[str, Any]:
    data: dict[str, Any] = {"version": 1, "sessions": {}}
    sessions: dict[str, dict[str, str]] = {}
    for chat_id, thread_id in mapping.items():
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            continue
        sessions[str(chat_id)] = {"thread_id": normalized_thread_id}
    data["sessions"] = sessions
    return data


def write_json_dict(path: Path, payload: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def load_thread_state_map(path: Path) -> dict[int, str]:
    raw = read_json_dict(path)
    sessions = raw.get("sessions", {})
    if not isinstance(sessions, dict):
        return {}
    out: dict[int, str] = {}
    for chat_key, payload in sessions.items():
        try:
            chat_id = int(chat_key)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        thread_id = str(payload.get("thread_id") or "").strip()
        if thread_id:
            out[chat_id] = thread_id
    return out


def normalize_telegram_parse_mode(parse_mode: object) -> str:
    normalized = str(parse_mode or "").strip().lower()
    if not normalized:
        return ""
    if normalized == "html":
        return "HTML"
    if normalized == "markdownv2":
        return "MarkdownV2"
    if normalized == "markdown":
        return "Markdown"
    return ""


def compact_prompt_text(value: object, max_len: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def strip_new_command_prefix(text: str) -> str:
    raw = str(text or "")
    return re.sub(r"^\s*/new(?:\s+|$)", "", raw, flags=re.IGNORECASE).strip()


def normalize_ui_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def extract_msg_id_token(text: str) -> int:
    normalized = str(text or "").strip()
    m = re.fullmatch(r"(?:msg_)?(\d+)", normalized, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return 0
    m2 = re.search(r"\bmsg_(\d+)\b", normalized, flags=re.IGNORECASE)
    if not m2:
        return 0
    try:
        return int(m2.group(1))
    except Exception:
        return 0


def normalize_task_id_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"msg_\d+", text, flags=re.IGNORECASE):
        return text.lower()
    if re.fullmatch(r"thread_[A-Za-z0-9._:-]+", text, flags=re.IGNORECASE):
        return text
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        text,
    ):
        return f"thread_{text}"
    if text.isdigit():
        return f"msg_{text}"
    return ""


def normalize_thread_id_token(value: object, *, compact_max_len: int = 220) -> str:
    candidate = compact_prompt_text(value, max_len=compact_max_len)
    if not candidate:
        return ""
    normalized = normalize_task_id_token(f"thread_{candidate}")
    if not normalized.lower().startswith("thread_"):
        return ""
    thread_id = normalized[len("thread_") :]
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        thread_id,
    ):
        return ""
    return thread_id


def split_text_chunks(text: str, max_chars: int = DEFAULT_TASK_GUIDE_TELEGRAM_CHUNK_CHARS) -> list[str]:
    rendered = str(text or "")
    if not rendered:
        return []
    limit = max(1, int(max_chars))
    chunks: list[str] = []
    buffer = ""
    for line in rendered.splitlines(keepends=True):
        if len(line) > limit:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            start = 0
            while start < len(line):
                chunks.append(line[start : start + limit])
                start += limit
            continue
        if len(buffer) + len(line) > limit and buffer:
            chunks.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        chunks.append(buffer)
    if not chunks:
        chunks.append(rendered[:limit])
    return chunks


def build_candidate_keyboard_rows(
    button_texts: list[str],
    *,
    main_menu_rows: list[list[str]],
    per_row: int = 1,
) -> list[list[str]]:
    rows: list[list[str]] = []
    normalized = [normalize_ui_text(v) for v in button_texts if normalize_ui_text(v)]
    if per_row <= 0:
        per_row = 1
    for idx in range(0, len(normalized), per_row):
        rows.append(normalized[idx : idx + per_row])
    rows.extend(main_menu_rows)
    return rows


def task_row_id(row: dict[str, Any]) -> str:
    task_id = normalize_task_id_token(row.get("task_id"))
    if task_id:
        return task_id
    thread_id = compact_prompt_text(row.get("thread_id", ""), max_len=120)
    if thread_id:
        normalized = normalize_task_id_token(f"thread_{thread_id}")
        if normalized:
            return normalized
    msg_id = int(row.get("message_id", 0) or 0)
    if msg_id > 0:
        return f"msg_{msg_id}"
    return ""


__all__ = [name for name in globals() if not name.startswith("__")]
