"Daemon service orchestration."
from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.service_config import DaemonServiceConfig
from sonolbot.core.daemon.service_telegram import DaemonServiceTelegramMixin

class DaemonService(DaemonServiceTelegramMixin):
    def __init__(self) -> None:
        self.config, init_warnings = DaemonServiceConfig.from_env()
        for name, value in self.config.as_dict().items():
            setattr(self, name, value)
        self.python_bin = self._detect_python_bin()
        self.codex_run_meta: Optional[dict[str, object]] = None
        self._telegram_runtime: Optional[dict[str, object]] = None
        self._telegram_skill = None
        self._task_skill = None
        self.stop_requested = False
        self.app_proc: Optional[subprocess.Popen[str]] = None
        self.app_proc_generation = 0
        self.app_json_send_lock = threading.Lock()
        self.app_req_lock = threading.Lock()
        self.app_pending_responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self.app_event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.app_next_request_id = 1
        self.app_chat_states: dict[int, dict[str, Any]] = {}
        self.app_thread_to_chat: dict[str, int] = {}
        self.app_turn_to_chat: dict[str, int] = {}
        self.app_aux_turn_results: dict[str, dict[str, Any]] = {}
        self.app_last_restart_try_epoch = 0.0
        self._process_lock: _ProcessFileLock | None = None
        self._app_server_lock_fd: int | None = None
        self._app_server_lock_busy_logged_at = 0.0
        self._owned_chat_leases: set[int] = set()
        self._chat_lease_busy_logged_at: dict[int, float] = {}
        self.completed_message_ids_recent: dict[int, float] = {}
        self._completed_requeue_log_ts: dict[int, float] = {}
        self.rewriter_proc: Optional[subprocess.Popen[str]] = None
        self.rewriter_json_send_lock = threading.Lock()
        self.rewriter_req_lock = threading.Lock()
        self.rewriter_pending_responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self.rewriter_event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.rewriter_next_request_id = 1
        self.rewriter_last_restart_try_epoch = 0.0
        self.rewriter_chat_threads: dict[int, str] = {}
        self.rewriter_turn_results: dict[str, dict[str, Any]] = {}
        self._agent_rewriter_lock_fd: int | None = None
        self._agent_rewriter_lock_busy_logged_at = 0.0

        self.env = os.environ.copy()
        self.env.setdefault("LANG", "C.UTF-8")
        self.env.setdefault("LC_ALL", "C.UTF-8")
        self.env.setdefault("PYTHONUTF8", "1")
        self.env.setdefault("PYTHONIOENCODING", "UTF-8")
        self.env["SONOLBOT_GUI_SESSION"] = "1" if self._has_gui_session() else "0"
        for message in init_warnings:
            self._log(f"WARN: {message}")

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.touch(exist_ok=True)
        self.codex_work_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.chat_locks_dir.mkdir(parents=True, exist_ok=True)
        self.agent_rewriter_workspace.mkdir(parents=True, exist_ok=True)
        self._harden_sensitive_permissions()
        self._load_app_server_state()
        self._load_agent_rewriter_state()
        self._cleanup_activity_logs()
        self._rotate_activity_log_if_needed(force=False)

    def _detect_python_bin(self) -> str:
        venv_py = self.root / ".venv" / "bin" / "python"
        if venv_py.exists():
            return str(venv_py)
        return sys.executable

    def _daily_log_path(self) -> Path:
        return self.logs_dir / f"daemon-{datetime.now().strftime('%Y-%m-%d')}.log"

    def _get_task_skill(self) -> object | None:
        if self._task_skill is not None:
            return self._task_skill
        try:
            skill = get_task_skill()
        except Exception as exc:
            self._log(f"WARN: task skill init failed: {exc}")
            return None
        self._task_skill = skill
        return skill

    def _run_task_commands_json(self, args: list[str], timeout_sec: float = 25.0) -> dict[str, Any] | None:
        cmd = [self.python_bin, "-m", "sonolbot.tools.task_commands", *args]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                env=self.env,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_sec,
            )
        except Exception as exc:
            self._log(f"WARN: task command failed args={args}: {exc}")
            return None

        stdout = str(proc.stdout or "").strip()
        stderr = str(proc.stderr or "").strip()
        if stderr:
            self._log(f"[task_commands][stderr] {stderr}")
        if not stdout:
            return None
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict):
                return payload
            return None
        except Exception as exc:
            self._log(f"WARN: task command json parse failed args={args}: {exc}")
            return None

    def _load_task_row(self, chat_id: int, task_id: str, include_instrunction: bool = False) -> dict[str, Any] | None:
        normalized_task_id = _service_utils.normalize_task_id_token(task_id)
        if not normalized_task_id:
            return None
        task_root = self._task_root_for_chat(chat_id)
        args = [
            "activate",
            normalized_task_id,
            "--tasks-dir",
            str(task_root),
            "--json",
        ]
        if include_instrunction:
            args.append("--include-instrunction")
        payload = self._run_task_commands_json(args)
        if not payload or not bool(payload.get("ok")):
            return None
        row = payload.get("task")
        if not isinstance(row, dict):
            return None
        return row

    def _task_row_recency_epoch(self, row: dict[str, Any]) -> float:
        latest_change = str(row.get("latest_change") or "").strip()
        if latest_change:
            ts_prefix = latest_change.split("|", 1)[0].strip()
            parsed = self._parse_datetime_epoch(ts_prefix)
            if parsed > 0:
                return parsed
        ts = self._parse_datetime_epoch(str(row.get("timestamp") or ""))
        if ts > 0:
            return ts
        task_dir = str(row.get("task_dir") or "").strip()
        if not task_dir:
            return 0.0
        try:
            return Path(task_dir).stat().st_mtime
        except OSError:
            return 0.0

    def _resolve_task_agents_thread_id(self, state: dict[str, Any]) -> str:
        current_thread_id = _service_utils.normalize_thread_id_token(state.get("thread_id"))
        if current_thread_id:
            return current_thread_id
        return _service_utils.normalize_thread_id_token(state.get("resume_target_thread_id"))

    def _task_agents_path(self, chat_id: int, thread_id: str) -> Path:
        normalized_thread_id = _service_utils.normalize_thread_id_token(thread_id)
        if not normalized_thread_id:
            raise ValueError("thread_id is required for task AGENTS path")
        task_root = self._task_root_for_chat(chat_id)
        return (task_root / f"thread_{normalized_thread_id}" / TASK_AGENTS_FILENAME).resolve()

    def _task_agents_relative_path(self, chat_id: int, thread_id: str) -> str:
        normalized_thread_id = _service_utils.normalize_thread_id_token(thread_id)
        if not normalized_thread_id:
            return ""
        if self.tasks_partition_by_chat:
            return f"tasks/chat_{chat_id}/thread_{normalized_thread_id}/{TASK_AGENTS_FILENAME}"
        return f"tasks/thread_{normalized_thread_id}/{TASK_AGENTS_FILENAME}"

    def _load_task_agents_text(self, chat_id: int, thread_id: str) -> tuple[str, bool]:
        path = self._task_agents_path(chat_id=chat_id, thread_id=thread_id)
        if not path.exists():
            return "", False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._log(f"WARN: failed to read task AGENTS.md path={path}: {exc}")
            return "", True
        return text, True

    def _build_task_agents_edit_request_text(self, target_path: Path, user_text: str) -> str:
        return (
            "다음 작업을 수행하세요.\n"
            f"- 대상 파일: {target_path}\n"
            "- 파일 이름은 반드시 AGENTS.md로 유지하세요.\n"
            "- 사용자의 변경 요청을 반영해 파일을 생성 또는 수정하세요.\n"
            "- 수정 후 어떤 항목을 바꿨는지 짧게 보고하세요.\n"
            "- 관련 없는 파일은 수정하지 마세요.\n\n"
            "[사용자 변경 요청]\n"
            f"{str(user_text or '').strip()}"
        )

    @staticmethod
    def _is_task_guide_edit_request_text(text: str) -> bool:
        normalized = _service_utils.normalize_ui_text(text).lower()
        if not normalized:
            return False
        if TASK_GUIDE_TRIGGER_TEXT not in normalized:
            return False
        if "보기" in normalized:
            return False
        return any(keyword in normalized for keyword in TASK_GUIDE_EDIT_KEYWORDS)

    def _default_task_agents_template(self, thread_id: str) -> str:
        normalized_thread_id = _service_utils.normalize_thread_id_token(thread_id)
        return (
            "# AGENTS.md\n\n"
            f"- Task Folder: thread_{normalized_thread_id}\n"
            "- Last Updated: (auto)\n\n"
            "## Task Guidance\n"
            "- (여기에 사용자 전용 TASK 지침을 작성하세요)\n"
        )

    def _ensure_task_agents_file(self, chat_id: int, thread_id: str) -> bool:
        path = self._task_agents_path(chat_id=chat_id, thread_id=thread_id)
        if path.exists():
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                self._default_task_agents_template(thread_id=thread_id),
                encoding="utf-8",
            )
            self._log(f"task_guide_created chat_id={chat_id} path={path}")
            return True
        except OSError as exc:
            self._log(f"WARN: failed to create task AGENTS.md path={path}: {exc}")
            return False

    def _forward_task_guide_edit_request(
        self,
        chat_id: int,
        state: dict[str, Any],
        item: dict[str, Any],
        msg_id: int,
        user_text: str,
    ) -> bool:
        target_thread_id = self._resolve_task_agents_thread_id(state)
        if not target_thread_id:
            self._clear_ui_mode(state)
            reply_text = (
                "현재 선택된 TASK가 없어 지침 변경 요청을 처리할 수 없습니다.\n"
                "먼저 `TASK 목록 보기(최근20)` 또는 `기존 TASK 이어하기`로 TASK를 선택해 주세요."
            )
            self._send_control_reply(
                chat_id=chat_id,
                message_id=msg_id,
                reply_text=reply_text,
                keyboard_rows=self._main_menu_keyboard_rows(),
                request_max_attempts=1,
            )
            return True

        target_path = self._task_agents_path(chat_id=chat_id, thread_id=target_thread_id)
        if not target_path.exists():
            if not self._ensure_task_agents_file(chat_id=chat_id, thread_id=target_thread_id):
                self._clear_ui_mode(state)
                reply_text = (
                    "TASK 지침 파일을 생성하는 중 문제가 발생했어요.\n"
                    "잠시 후 다시 시도해 주세요."
                )
                self._send_control_reply(
                    chat_id=chat_id,
                    message_id=msg_id,
                    reply_text=reply_text,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
                return True

        rewritten_request = self._build_task_agents_edit_request_text(
            target_path=target_path,
            user_text=user_text,
        )
        item["text"] = rewritten_request
        self._clear_ui_mode(state)
        self._log(
            f"task_guide_edit_forwarded chat_id={chat_id} msg_id={msg_id} "
            f"target={target_path}"
        )
        return False

    def _load_task_agents_developer_instructions(self, chat_id: int, state: dict[str, Any]) -> str:
        thread_id = self._resolve_task_agents_thread_id(state)
        if not thread_id:
            return ""
        content, exists = self._load_task_agents_text(chat_id=chat_id, thread_id=thread_id)
        if not exists:
            path = self._task_agents_path(chat_id=chat_id, thread_id=thread_id)
            self._log(f"task_guide_missing_for_developer_instructions chat_id={chat_id} path={path}")
            return ""
        normalized = str(content or "").strip()
        if not normalized:
            return ""
        if len(normalized) > DEFAULT_TASK_AGENTS_INSTRUCTIONS_MAX_CHARS:
            self._log(
                "WARN: task AGENTS.md too long for developerInstructions; "
                f"truncating to {DEFAULT_TASK_AGENTS_INSTRUCTIONS_MAX_CHARS} chars"
            )
            normalized = normalized[:DEFAULT_TASK_AGENTS_INSTRUCTIONS_MAX_CHARS]
        return normalized

    def _list_recent_tasks(self, chat_id: int, limit: int = 20, source_limit: int = 200) -> list[dict[str, Any]]:
        task_root = self._task_root_for_chat(chat_id)
        payload = self._run_task_commands_json(
            [
                "list",
                "--tasks-dir",
                str(task_root),
                "--limit",
                str(max(limit, source_limit)),
                "--json",
            ]
        )
        if not payload:
            return []
        rows = payload.get("tasks", [])
        if not isinstance(rows, list):
            return []
        normalized: list[dict[str, Any]] = [row for row in rows if isinstance(row, dict)]
        normalized.sort(
            key=lambda row: (
                self._task_row_recency_epoch(row),
                _service_utils.task_row_id(row),
            ),
            reverse=True,
        )
        return normalized[: max(1, int(limit))]

    def _recover_latest_thread_id_for_chat(self, chat_id: int) -> str:
        rows = self._list_recent_tasks(chat_id=chat_id, limit=20, source_limit=120)
        for row in rows:
            thread_id = _service_utils.compact_prompt_text(row.get("thread_id", ""), max_len=220)
            if not thread_id:
                task_id = _service_utils.task_row_id(row)
                if task_id.startswith("thread_"):
                    thread_id = task_id[len("thread_") :]
            if thread_id:
                return thread_id
        return ""

    def _render_task_list_text(self, rows: list[dict[str, Any]], limit: int = 20) -> str:
        lines = [
            f"<b>TASK 목록 (최근 {int(limit)}개)</b>",
            "<i>최근순으로 정렬됩니다.</i>",
            "",
        ]
        for idx, row in enumerate(rows, start=1):
            lines.extend(
                self._build_task_card_lines(
                    idx,
                    row,
                    subtitle_max_len=64,
                    include_blank_line=True,
                )
            )
        return "\n".join(lines).strip()

    def _send_task_cards_batch(
        self,
        chat_id: int,
        rows: list[dict[str, Any]],
        header_text: str = "",
        footer_text: str = "",
        *,
        parse_mode: str | None = "HTML",
        request_max_attempts: int = 1,
    ) -> bool:
        sent = False
        if header_text:
            sent = bool(
                self._telegram_send_text(
                    chat_id=chat_id,
                    text=header_text,
                    keyboard_rows=None,
                    inline_keyboard_rows=None,
                    request_max_attempts=request_max_attempts,
                    parse_mode=parse_mode,
                )
            )
        for idx, row in enumerate(rows, start=1):
            row_task_id = _service_utils.task_row_id(row)
            if not row_task_id:
                continue
            item_text = self._render_task_item_card_text(idx=idx, row=row)
            item_inline_keyboard = self._build_single_task_inline_select_keyboard(task_id=row_task_id)
            sent_item = self._telegram_send_text(
                chat_id=chat_id,
                text=item_text,
                keyboard_rows=None,
                inline_keyboard_rows=item_inline_keyboard,
                request_max_attempts=request_max_attempts,
                parse_mode=parse_mode,
            )
            sent = bool(sent or sent_item)
        if footer_text:
            sent_footer = self._telegram_send_text(
                chat_id=chat_id,
                text=footer_text,
                keyboard_rows=None,
                inline_keyboard_rows=None,
                request_max_attempts=request_max_attempts,
            )
            sent = bool(sent or sent_footer)
        return sent

    def _build_task_card_lines(
        self,
        idx: int,
        row: dict[str, Any],
        *,
        subtitle_max_len: int = 64,
        include_score: bool = False,
        include_blank_line: bool = False,
        subtitle_fallback_fields: tuple[str, ...] = ("display_subtitle", "result_summary_short", "instruction_short"),
    ) -> list[str]:
        title = _service_utils.compact_prompt_text(
            row.get("display_title", "") or row.get("instruction", "") or row.get("instruction_short", ""),
            max_len=44,
        ) or "(제목 없음)"
        subtitle = ""
        for field in subtitle_fallback_fields:
            value = row.get(field, "")
            raw_value = str(value).strip() if value is not None else ""
            if raw_value:
                subtitle = _service_utils.compact_prompt_text(raw_value, max_len=subtitle_max_len)
                break
        work_status_badge = self._render_user_work_status_badge(row.get("work_status", "") or row.get("status", ""))
        recent_ts = _service_utils.compact_prompt_text(self._task_row_recent_timestamp(row), max_len=19) or "-"
        title_html = self._escape_telegram_html(title)
        subtitle_html = self._escape_telegram_html(subtitle) if subtitle else "-"
        work_html = self._escape_telegram_html(work_status_badge)
        recent_html = self._escape_telegram_html(recent_ts)
        lines = [
            f"<b>{idx}. {title_html}</b>",
            f"<b>요약</b>: {subtitle_html}",
            f"<b>상태</b>: {work_html}",
            f"<b>최근</b>: <code>{recent_html}</code>",
        ]
        if include_score:
            try:
                relevance_score = int(row.get("relevance_score", -1))
            except Exception:
                relevance_score = -1
            if relevance_score >= 0:
                lines.append(f"<b>연관도</b>: <code>{int(relevance_score)}점</code>")
        if include_blank_line:
            lines.append("")
        return lines

    def _render_task_item_card_text(self, idx: int, row: dict[str, Any]) -> str:
        return "\n".join(
            self._build_task_card_lines(
                int(idx),
                row,
                include_score=True,
                include_blank_line=False,
            )
        ).strip()

    def _render_task_candidates_text(self, query: str, rows: list[dict[str, Any]]) -> str:
        query_html = self._escape_telegram_html(query)
        lines = [
            "<b>연관 TASK 후보</b>",
            f"검색어: <code>{query_html}</code>",
            "<i>번호를 입력하거나 아래 버튼에서 선택해 주세요.</i>",
            "",
        ]
        for idx, row in enumerate(rows, start=1):
            lines.extend(
                self._build_task_card_lines(
                    idx,
                    row,
                    subtitle_max_len=52,
                    include_score=True,
                    include_blank_line=True,
                    subtitle_fallback_fields=("display_subtitle", "result_summary_short"),
                )
            )
        return "\n".join(lines).strip()

    def _task_row_recent_timestamp(self, row: dict[str, Any]) -> str:
        latest_change = str(row.get("latest_change") or "").strip()
        if latest_change:
            prefix = latest_change.split("|", 1)[0].strip()
            if self._parse_datetime_epoch(prefix) > 0:
                return prefix
        title_updated = str(row.get("title_updated_at") or "").strip()
        if title_updated and self._parse_datetime_epoch(title_updated) > 0:
            return title_updated
        ts = str(row.get("timestamp") or "").strip()
        if ts and self._parse_datetime_epoch(ts) > 0:
            return ts
        return ""

    @staticmethod
    def _parse_json_object_from_text(raw_text: str) -> dict[str, Any] | None:
        text = str(raw_text or "").strip()
        if not text:
            return None
        candidates: list[str] = [text]
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fence_match:
            candidates.append(str(fence_match.group(1)).strip())
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(text[first_brace : last_brace + 1].strip())
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _build_task_search_llm_prompt(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        limit: int,
        min_score: int,
    ) -> str:
        compact_candidates: list[dict[str, Any]] = []
        for row in candidates:
            task_id = _service_utils.task_row_id(row)
            if not task_id:
                continue
            title = _service_utils.compact_prompt_text(
                row.get("display_title", "") or row.get("instruction", "") or row.get("instruction_short", ""),
                max_len=70,
            ) or "(제목 없음)"
            summary = _service_utils.compact_prompt_text(
                row.get("display_subtitle", "") or row.get("result_summary_short", "") or row.get("instruction_short", ""),
                max_len=140,
            )
            compact_candidates.append(
                {
                    "task_id": task_id,
                    "title": title,
                    "summary": summary,
                    "recent_at": self._task_row_recent_timestamp(row),
                    "status": self._render_user_work_status(row.get("work_status", "") or row.get("status", "")),
                }
            )
        request_payload = {
            "version": 1,
            "query": _service_utils.normalize_ui_text(query),
            "top_k": int(limit),
            "min_score": int(min_score),
            "candidates": compact_candidates,
        }
        instructions = [
            "당신은 TASK 검색 랭커다.",
            "목표: query와 가장 관련성 높은 TASK를 candidates 내부에서만 고른다.",
            "중요 규칙:",
            "1) candidates에 없는 task_id는 절대 출력하지 않는다.",
            "2) score는 0~100 정수로 부여한다.",
            "3) score 높은 순으로 정렬한다.",
            "4) 출력은 JSON 객체 하나만 출력한다. 코드블록/설명문/추가 텍스트 금지.",
            '5) 출력 스키마: {"version":1,"query":"...","results":[{"task_id":"...","score":87,"reason":"짧은 근거"}]}',
            "6) results는 top_k 이내로 제한한다.",
            "",
            "입력 JSON:",
            json.dumps(request_payload, ensure_ascii=False),
        ]
        return "\n".join(instructions).strip()

    def _app_run_aux_turn_for_json(self, prompt_text: str, timeout_sec: float) -> dict[str, Any] | None:
        if not str(prompt_text or "").strip():
            return None
        if not self._ensure_app_server():
            return None
        started_thread = self._app_request(
            "thread/start",
            {
                "cwd": str(self.codex_work_dir),
                "approvalPolicy": self.app_server_approval_policy,
                "sandbox": self.app_server_sandbox,
                "model": self.codex_model,
            },
            timeout_sec=self.task_search_llm_request_timeout_sec,
        )
        if started_thread is None:
            return None
        thread = started_thread.get("thread")
        if not isinstance(thread, dict):
            return None
        thread_id = str(thread.get("id") or "").strip()
        if not thread_id:
            return None

        started_turn = self._app_request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": str(prompt_text)}],
                "model": self.codex_model,
                "effort": self.codex_reasoning_effort,
                "approvalPolicy": self.app_server_approval_policy,
            },
            timeout_sec=self.task_search_llm_request_timeout_sec,
        )
        if started_turn is None:
            return None

        turn = started_turn.get("turn")
        turn_id = ""
        if isinstance(turn, dict):
            turn_id = str(turn.get("id") or "").strip()
        if not turn_id:
            turn_id = str(started_turn.get("turnId") or "").strip()
        if not turn_id:
            return None

        self.app_aux_turn_results[turn_id] = {
            "status": "started",
            "text": "",
            "thread_id": thread_id,
            "updated_at": time.time(),
        }
        deadline = time.time() + max(1.0, float(timeout_sec))
        while time.time() < deadline:
            self._app_drain_events(max_items=200)
            current = self.app_aux_turn_results.get(turn_id)
            if isinstance(current, dict):
                status = str(current.get("status") or "").strip().lower()
                text = str(current.get("text") or "").strip()
                if status in {"failed", "cancelled", "error", "errored"}:
                    self.app_aux_turn_results.pop(turn_id, None)
                    return None
                if status == "completed" and text:
                    self.app_aux_turn_results.pop(turn_id, None)
                    return self._parse_json_object_from_text(text)
            if not self._app_is_running():
                break
            time.sleep(0.05)
        self.app_aux_turn_results.pop(turn_id, None)
        return None

    def _search_task_candidates_via_llm(self, chat_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
        normalized_query = _service_utils.normalize_ui_text(query)
        if not normalized_query:
            return []
        candidate_pool = self._list_recent_tasks(
            chat_id=chat_id,
            limit=max(limit, self.task_search_llm_candidate_pool_limit),
            source_limit=max(self.task_search_llm_candidate_pool_limit * 2, 120),
        )
        if not candidate_pool:
            return []

        deduped_candidates: list[dict[str, Any]] = []
        row_by_task_id: dict[str, dict[str, Any]] = {}
        for row in candidate_pool:
            task_id = _service_utils.task_row_id(row)
            if not task_id or task_id in row_by_task_id:
                continue
            row_by_task_id[task_id] = row
            deduped_candidates.append(row)
        if not deduped_candidates:
            return []

        prompt = self._build_task_search_llm_prompt(
            query=normalized_query,
            candidates=deduped_candidates,
            limit=max(1, int(limit)),
            min_score=int(self.task_search_llm_min_score),
        )
        parsed = self._app_run_aux_turn_for_json(
            prompt_text=prompt,
            timeout_sec=self.task_search_llm_turn_timeout_sec,
        )
        if not isinstance(parsed, dict):
            return []

        raw_results = parsed.get("results")
        if not isinstance(raw_results, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            task_id = _service_utils.normalize_task_id_token(item.get("task_id"))
            if not task_id or task_id in seen or task_id not in row_by_task_id:
                continue
            score_raw = item.get("score")
            try:
                score = int(score_raw)
            except Exception:
                continue
            if score < 0:
                score = 0
            if score > 100:
                score = 100
            if score < int(self.task_search_llm_min_score):
                continue
            row = dict(row_by_task_id[task_id])
            row["relevance_score"] = score
            reason = _service_utils.compact_prompt_text(item.get("reason", ""), max_len=120)
            if reason:
                row["relevance_reason"] = reason
            out.append(row)
            seen.add(task_id)
            if len(out) >= max(1, int(limit)):
                break
        out.sort(
            key=lambda row: (
                int(row.get("relevance_score", 0) or 0),
                self._task_row_recency_epoch(row),
            ),
            reverse=True,
        )
        return out[: max(1, int(limit))]

    def _search_task_candidates_for_resume(self, chat_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
        effective_limit = max(1, min(int(limit), int(self.task_search_llm_limit)))
        if self.task_search_llm_enabled:
            candidates = self._search_task_candidates_via_llm(
                chat_id=chat_id,
                query=query,
                limit=effective_limit,
            )
            if candidates:
                self._log(
                    f"resume_search llm_ok chat_id={chat_id} query={_service_utils.compact_prompt_text(query, max_len=80)!r} "
                    f"count={len(candidates)} threshold={self.task_search_llm_min_score}"
                )
                return candidates
            self._log(
                f"WARN: resume_search llm_empty_or_failed chat_id={chat_id} "
                f"query={_service_utils.compact_prompt_text(query, max_len=80)!r}; fallback=code"
            )
        return self._search_task_candidates(chat_id=chat_id, query=query, limit=effective_limit)

    def _search_task_candidates(self, chat_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
        task_root = self._task_root_for_chat(chat_id)
        normalized_query = _service_utils.normalize_ui_text(query)
        if not normalized_query:
            return []

        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        task_skill = self._get_task_skill()
        if task_skill is not None and hasattr(task_skill, "find_relevant_tasks"):
            try:
                related = task_skill.find_relevant_tasks(
                    query=normalized_query,
                    tasks_dir=str(task_root),
                    limit=max(limit * 3, 10),
                    logs_dir=str(self.logs_dir),
                )
            except Exception as exc:
                self._log(f"WARN: relevant task search failed chat_id={chat_id}: {exc}")
                related = []
            if isinstance(related, list):
                for item in related:
                    if not isinstance(item, dict):
                        continue
                    candidate_task_id = _service_utils.normalize_task_id_token(item.get("task_id"))
                    if not candidate_task_id:
                        thread_id = _service_utils.compact_prompt_text(item.get("thread_id", ""), max_len=200)
                        if thread_id:
                            candidate_task_id = _service_utils.normalize_task_id_token(f"thread_{thread_id}")
                    if not candidate_task_id:
                        msg_id = int(item.get("message_id", 0) or 0)
                        if msg_id > 0:
                            candidate_task_id = f"msg_{msg_id}"
                    if not candidate_task_id or candidate_task_id in seen_ids:
                        continue
                    row = self._load_task_row(chat_id=chat_id, task_id=candidate_task_id, include_instrunction=False)
                    if not row:
                        continue
                    resolved_id = _service_utils.task_row_id(row) or candidate_task_id
                    seen_ids.add(resolved_id)
                    results.append(row)
                    if len(results) >= limit:
                        return results[:limit]

        payload = self._run_task_commands_json(
            [
                "list",
                "--tasks-dir",
                str(task_root),
                "--keyword",
                normalized_query,
                "--limit",
                str(max(limit * 4, 20)),
                "--json",
            ]
        )
        if not payload:
            return results[:limit]

        rows = payload.get("tasks", [])
        if not isinstance(rows, list):
            return results[:limit]
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = _service_utils.task_row_id(row)
            if not task_id or task_id in seen_ids:
                continue
            seen_ids.add(task_id)
            results.append(row)
            if len(results) >= limit:
                break
        return results[:limit]

    def _resolve_task_choice(self, text: str, candidates: list[str], candidate_map: dict[str, str] | None = None) -> str:
        normalized = _service_utils.normalize_ui_text(text)
        if not normalized:
            return ""
        candidate_ids = [_service_utils.normalize_task_id_token(v) for v in candidates]
        candidate_ids = [v for v in candidate_ids if v]
        map_raw = candidate_map if isinstance(candidate_map, dict) else {}
        normalized_map = {
            _service_utils.normalize_ui_text(str(k)): _service_utils.normalize_task_id_token(v)
            for k, v in map_raw.items()
        }

        mapped = normalized_map.get(normalized)
        if mapped and mapped in candidate_ids:
            return mapped
        idx_match = re.match(r"^(\d+)\s*[\).:\-]?", normalized)
        if idx_match:
            idx = int(idx_match.group(1))
            if 1 <= idx <= len(candidate_ids):
                return str(candidate_ids[idx - 1])
        direct_task_id = _service_utils.normalize_task_id_token(normalized)
        if direct_task_id and direct_task_id in candidate_ids:
            return direct_task_id
        direct_msg_id = _service_utils.extract_msg_id_token(normalized)
        if direct_msg_id > 0:
            direct_msg_task = f"msg_{direct_msg_id}"
            if direct_msg_task in candidate_ids:
                return direct_msg_task
        if normalized.isdigit():
            idx = int(normalized)
            if 1 <= idx <= len(candidate_ids):
                return str(candidate_ids[idx - 1])
        return ""

    def _set_selected_task_state(self, chat_id: int, state: dict[str, Any], row: dict[str, Any]) -> None:
        task_id = _service_utils.task_row_id(row)
        if not task_id:
            msg_id = int(row.get("message_id", 0) or 0)
            if msg_id > 0:
                task_id = f"msg_{msg_id}"
        status = _service_utils.compact_prompt_text(row.get("work_status", "") or row.get("status", ""), max_len=28) or "unknown"
        ops_status = _service_utils.compact_prompt_text(row.get("ops_status", ""), max_len=28) or "unknown"
        title = _service_utils.compact_prompt_text(
            row.get("display_title", "") or row.get("instruction", "") or row.get("instruction_short", ""),
            max_len=120,
        ) or "(제목 없음)"
        subtitle = _service_utils.compact_prompt_text(
            row.get("display_subtitle", "") or row.get("result_summary_short", "") or row.get("instruction_short", ""),
            max_len=220,
        )
        instruction = _service_utils.compact_prompt_text(row.get("instruction", ""), max_len=220) or "(지시 없음)"
        latest_change = _service_utils.compact_prompt_text(row.get("latest_change", ""), max_len=240)
        recent_ts = _service_utils.compact_prompt_text(self._task_row_recent_timestamp(row), max_len=19)
        related_ids = row.get("related_task_ids", [])
        if not isinstance(related_ids, list):
            related_ids = []
        related_text = ", ".join(_service_utils.compact_prompt_text(v, max_len=100) for v in related_ids[:8] if str(v).strip())
        task_thread_id = _service_utils.compact_prompt_text(row.get("thread_id", ""), max_len=200)
        if not task_thread_id and task_id and task_id.startswith("thread_"):
            task_thread_id = task_id[len("thread_") :]
        if not task_thread_id and task_id:
            task_thread_id = self._lookup_mapped_thread_id(chat_id=chat_id, task_id=task_id)
        if task_thread_id and task_id:
            self._bind_task_thread_mapping(chat_id=chat_id, task_id=task_id, thread_id=task_thread_id)

        lines = [
            "[이어갈 TASK 컨텍스트]",
            f"- task: {task_id or '(unknown)'}",
            f"- title: {title}",
            f"- status: {status} (ops={ops_status})",
        ]
        if subtitle:
            lines.append(f"- summary: {subtitle}")
        if recent_ts:
            lines.append(f"- recent_at: {recent_ts}")
        if task_thread_id:
            lines.append(f"- thread_id: {task_thread_id}")
        lines += [
            f"- instruction: {instruction}",
        ]
        if latest_change:
            lines.append(f"- latest_change: {latest_change}")
        if related_text:
            lines.append(f"- related: {related_text}")
        lines.append("- 지시사항을 위 TASK 맥락으로 이어서 처리할 것.")
        packet = "\n".join(lines)
        if len(packet) > 1500:
            packet = packet[:1497] + "..."

        state["selected_task_id"] = task_id
        state["selected_task_packet"] = packet
        state["resume_target_thread_id"] = task_thread_id
        state["resume_thread_switch_pending"] = bool(task_id)

    def _clear_selected_task_state(self, state: dict[str, Any]) -> None:
        state["selected_task_id"] = ""
        state["selected_task_packet"] = ""
        state["resume_target_thread_id"] = ""
        state["resume_thread_switch_pending"] = False
        state["resume_recent_chat_summary_once"] = ""
        state["resume_context_inject_once"] = False

    def _build_new_task_carryover_summary(self, chat_id: int, state: dict[str, Any]) -> str:
        rows = self._list_recent_tasks(chat_id=chat_id, limit=20, source_limit=200)
        if not rows:
            return ""

        selected_task_id = _service_utils.normalize_task_id_token(state.get("selected_task_id"))
        anchor_task_id = ""
        if selected_task_id:
            for row in rows:
                row_task_id = _service_utils.task_row_id(row)
                if row_task_id == selected_task_id:
                    anchor_task_id = selected_task_id
                    break
        if not anchor_task_id and rows:
            anchor_task_id = _service_utils.task_row_id(rows[0])
        if not anchor_task_id:
            return ""

        anchor_row = self._load_task_row(chat_id=chat_id, task_id=anchor_task_id, include_instrunction=True) or {}
        instruction_text = str(anchor_row.get("instruction_text") or "").strip()
        instruction_short = _service_utils.compact_prompt_text(anchor_row.get("instruction", ""), max_len=220)
        anchor_title = _service_utils.compact_prompt_text(anchor_row.get("display_title", ""), max_len=120)
        anchor_subtitle = _service_utils.compact_prompt_text(anchor_row.get("display_subtitle", ""), max_len=160)
        latest_change = _service_utils.compact_prompt_text(anchor_row.get("latest_change", ""), max_len=220)

        target_lines = max(10, int(self.new_task_summary_lines))
        lines: list[str] = [
            "[이전 대화 핵심 요약(자동)]",
            f"- 기준 TASK: {anchor_task_id}",
        ]
        if anchor_title:
            lines.append(f"- 기준 제목: {anchor_title}")
        if anchor_subtitle:
            lines.append(f"- 기준 요약: {anchor_subtitle}")
        if instruction_short:
            lines.append(f"- 기준 지시: {instruction_short}")
        if latest_change:
            lines.append(f"- 최근 변경: {latest_change}")
        lines.append("")
        lines.append("[핵심 맥락]")

        if instruction_text:
            for raw in instruction_text.splitlines():
                compact = _service_utils.compact_prompt_text(raw, max_len=180)
                if not compact:
                    continue
                lines.append(compact)
                if len(lines) >= int(target_lines * 0.72):
                    break

        lines.append("")
        lines.append("[최근 TASK 흐름]")
        for row in rows:
            row_task_id = _service_utils.task_row_id(row) or "(unknown)"
            work_status = _service_utils.compact_prompt_text(row.get("work_status", "") or row.get("status", ""), max_len=24) or "unknown"
            ops_status = _service_utils.compact_prompt_text(row.get("ops_status", ""), max_len=24) or "unknown"
            title = _service_utils.compact_prompt_text(
                row.get("display_title", "") or row.get("instruction", "") or row.get("instruction_short", ""),
                max_len=70,
            ) or "(제목 없음)"
            subtitle = _service_utils.compact_prompt_text(
                row.get("display_subtitle", "") or row.get("result_summary_short", ""),
                max_len=56,
            )
            recent_ts = _service_utils.compact_prompt_text(self._task_row_recent_timestamp(row), max_len=19) or "-"
            if subtitle:
                lines.append(f"- {row_task_id} | {title} | {subtitle} | {work_status}/{ops_status} | {recent_ts}")
            else:
                lines.append(f"- {row_task_id} | {title} | {work_status}/{ops_status} | {recent_ts}")
            if len(lines) >= target_lines:
                break

        rendered = "\n".join(lines[:target_lines]).strip()
        max_chars = max(1200, int(self.new_task_summary_max_chars))
        if len(rendered) > max_chars:
            rendered = rendered[: max_chars - 3] + "..."
        return rendered

    def _build_recent_chat_summary(
        self,
        chat_id: int,
        *,
        hours: int = DEFAULT_RESUME_CHAT_SUMMARY_HOURS,
        target_lines: int = DEFAULT_RESUME_CHAT_SUMMARY_LINES,
        max_chars: int = DEFAULT_RESUME_CHAT_SUMMARY_MAX_CHARS,
        exclude_message_id: int | None = None,
    ) -> str:
        now_epoch = time.time()
        window_hours = max(1, int(hours))
        cutoff_epoch = now_epoch - float(window_hours * 3600)
        target = max(10, int(target_lines))
        char_limit = max(1200, int(max_chars))

        lines: list[str] = [
            "[현재 챗 최근 대화 요약(자동)]",
            f"- 범위: 최근 {window_hours}시간",
            f"- 목표 줄수: 약 {target}줄 (메시지가 적으면 더 짧을 수 있음)",
            "",
            "[대화 흐름]",
        ]

        try:
            payload = json.loads(self.store_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"WARN: recent chat summary load failed chat_id={chat_id}: {exc}")
            lines.append("- 메시지 저장소를 읽지 못해 요약을 생성하지 못했습니다.")
            return "\n".join(lines).strip()

        raw_messages = payload.get("messages", []) if isinstance(payload, dict) else []
        if not isinstance(raw_messages, list):
            raw_messages = []

        filtered: list[tuple[float, int, dict[str, Any]]] = []
        for idx, raw in enumerate(raw_messages):
            if not isinstance(raw, dict):
                continue
            try:
                row_chat_id = int(raw.get("chat_id"))
            except Exception:
                continue
            if row_chat_id != int(chat_id):
                continue

            msg_type = str(raw.get("type") or "").strip().lower() or "user"
            if exclude_message_id is not None and msg_type == "user":
                try:
                    if int(raw.get("message_id")) == int(exclude_message_id):
                        continue
                except Exception:
                    pass

            ts_text = str(raw.get("timestamp") or "").strip()
            ts_epoch = self._parse_datetime_epoch(ts_text)
            if ts_epoch <= 0 or ts_epoch < cutoff_epoch:
                continue
            filtered.append((ts_epoch, idx, raw))

        filtered.sort(key=lambda item: (item[0], item[1]))
        if not filtered:
            lines.append("- 최근 대화가 없습니다.")
            return "\n".join(lines).strip()

        max_entries = max(target * 3, 90)
        omitted = 0
        if len(filtered) > max_entries:
            omitted = len(filtered) - max_entries
            filtered = filtered[-max_entries:]
        lines.insert(3, f"- 포함 메시지: {len(filtered)}개")
        if omitted > 0:
            lines.insert(4, f"- 오래된 항목 생략: {omitted}개")

        for _, _, raw in filtered:
            msg_type = str(raw.get("type") or "").strip().lower() or "user"
            ts_text = _service_utils.compact_prompt_text(raw.get("timestamp", ""), max_len=19) or "-"
            text = _service_utils.compact_prompt_text(raw.get("text", ""), max_len=180)

            files = raw.get("files")
            file_count = len(files) if isinstance(files, list) else 0
            location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
            suffix_parts: list[str] = []
            if file_count > 0:
                suffix_parts.append(f"첨부 {file_count}개")
            if location:
                lat = location.get("latitude")
                lon = location.get("longitude")
                if lat is not None and lon is not None:
                    suffix_parts.append(f"위치 {lat},{lon}")
            suffix = f" [{' / '.join(suffix_parts)}]" if suffix_parts else ""

            if not text:
                text = "(텍스트 없음)"

            if msg_type == "bot":
                speaker = "BOT"
            else:
                name = _service_utils.compact_prompt_text(raw.get("first_name", ""), max_len=20) or _service_utils.compact_prompt_text(
                    raw.get("username", ""), max_len=20
                )
                speaker = f"USER({name})" if name else "USER"
            lines.append(f"- [{ts_text}] {speaker}: {text}{suffix}")

        rendered = "\n".join(lines).strip()
        if len(rendered) > char_limit:
            rendered = rendered[: char_limit - 3] + "..."
        return rendered

    def _apply_selected_task_thread_target(self, chat_id: int, state: dict[str, Any]) -> None:
        if not bool(state.get("resume_thread_switch_pending")):
            return

        target_thread_id = str(state.get("resume_target_thread_id") or "").strip()
        current_thread_id = str(state.get("thread_id") or "").strip()
        selected_task_id = _service_utils.normalize_task_id_token(state.get("selected_task_id"))
        state["resume_thread_switch_pending"] = False
        state["resume_target_thread_id"] = ""

        if not target_thread_id and selected_task_id:
            target_thread_id = self._lookup_mapped_thread_id(chat_id=chat_id, task_id=selected_task_id)

        if target_thread_id:
            if current_thread_id and current_thread_id != target_thread_id:
                self.app_thread_to_chat.pop(current_thread_id, None)
            state["thread_id"] = target_thread_id
            state["app_generation"] = 0
            state["force_new_thread_once"] = False
            self._save_app_server_state()
            self._sync_app_server_session_meta(active_chat_id=chat_id)
            if selected_task_id:
                self._bind_task_thread_mapping(
                    chat_id=chat_id,
                    task_id=selected_task_id,
                    thread_id=target_thread_id,
                )
            self._log(f"task thread target applied chat_id={chat_id} thread_id={target_thread_id}")
            return

        state["force_new_thread_once"] = True
        self._save_app_server_state()
        self._log(f"task thread target missing, will start new thread chat_id={chat_id}")

    def _process_chat_control_messages(
        self,
        chat_id: int,
        state: dict[str, Any],
        pending_chat_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not pending_chat_messages:
            return pending_chat_messages

        mode = str(state.get("ui_mode") or UI_MODE_IDLE)
        expires_at = float(state.get("ui_mode_expires_at") or 0.0)
        if mode != UI_MODE_IDLE and expires_at > 0 and time.time() > expires_at:
            if mode == UI_MODE_AWAITING_TEMP_TASK_DECISION:
                self._clear_temp_task_seed(state)
            self._clear_ui_mode(state)

        remaining: list[dict[str, Any]] = []
        for item in pending_chat_messages:
            if self._handle_single_control_message(chat_id=chat_id, state=state, item=item):
                continue
            remaining.append(item)
        return remaining

    def _handle_single_control_message(
        self,
        chat_id: int,
        state: dict[str, Any],
        item: dict[str, Any],
    ) -> bool:
        msg_id = int(item.get("message_id", 0) or 0)
        message_id = msg_id
        text = _service_utils.normalize_ui_text(str(item.get("text", "")))
        callback_selected_task_id = self._extract_callback_task_select_id(text)
        if msg_id <= 0 or not text:
            return False

        current_mode = str(state.get("ui_mode") or UI_MODE_IDLE)
        reply_text = ""
        keyboard_rows: list[list[str]] | None = None
        if text.startswith("__cb__:") and current_mode != UI_MODE_AWAITING_RESUME_CHOICE:
            reply_text = "선택 가능한 목록이 만료되었어요. `TASK 목록 보기(최근20)`를 다시 눌러 주세요."
            keyboard_rows = self._main_menu_keyboard_rows()
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            return True

        if text == BUTTON_TASK_LIST_RECENT20:
            self._clear_temp_task_seed(state)
            rows = self._list_recent_tasks(chat_id=chat_id, limit=20, source_limit=300)
            if not rows:
                self._clear_ui_mode(state)
                reply_text = "최근 TASK 20개를 보여드리려 했지만, 조회된 TASK가 없습니다."
                keyboard_rows = self._main_menu_keyboard_rows()
                inline_keyboard_rows = None
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    inline_keyboard_rows=inline_keyboard_rows,
                    request_max_attempts=1,
                    parse_mode="HTML",
                )
            else:
                candidate_ids, candidate_buttons, candidate_map = self._build_resume_choice_payload(rows=rows, max_count=20)
                state["resume_choice_inline_only"] = True
                state["resume_candidates"] = candidate_ids
                state["resume_candidate_buttons"] = candidate_buttons
                state["resume_candidate_map"] = candidate_map
                self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
                header_text = self._render_task_list_text(rows=[], limit=20)
                footer_text = "최근순으로 정렬됩니다. 특정 작업(TASK)을 이어 진행하시려면 하단의 선택 버튼을 눌러 주세요."
                reply_text = footer_text
                sent = self._send_task_cards_batch(
                    chat_id=chat_id,
                    rows=rows,
                    header_text=header_text,
                    footer_text=footer_text,
                    parse_mode="HTML",
                )
            self._finalize_control_message_if_sent(chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent)
            return True

        if text == BUTTON_TASK_GUIDE_VIEW:
            self._clear_temp_task_seed(state)
            guide_thread_id = self._resolve_task_agents_thread_id(state)
            if not guide_thread_id:
                self._clear_ui_mode(state)
                reply_text = (
                    "현재 선택된 TASK가 없습니다.\n"
                    "먼저 `TASK 목록 보기(최근20)` 또는 `기존 TASK 이어하기`로 TASK를 선택해 주세요."
                )
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
                return True

            relative_path = self._task_agents_relative_path(chat_id=chat_id, thread_id=guide_thread_id)
            guide_text, exists = self._load_task_agents_text(chat_id=chat_id, thread_id=guide_thread_id)
            self._set_ui_mode(state, UI_MODE_AWAITING_TASK_GUIDE_EDIT)
            sent = False
            if exists and guide_text.strip():
                header_text = (
                    f"<b>TASK 지침 파일 보기</b>\n"
                    f"- 파일: <code>{self._escape_telegram_html(relative_path)}</code>\n"
                    "- 아래 내용 확인 후 변경 요청을 바로 보내주세요."
                )
                sent_header = self._telegram_send_text(
                    chat_id=chat_id,
                    text=header_text,
                    keyboard_rows=None,
                    request_max_attempts=1,
                    parse_mode="HTML",
                )
                sent = bool(sent or sent_header)
                chunks = _service_utils.split_text_chunks(guide_text, max_chars=DEFAULT_TASK_GUIDE_TELEGRAM_CHUNK_CHARS)
                total_chunks = len(chunks)
                for idx, chunk in enumerate(chunks, start=1):
                    chunk_label = f"TASK 지침 내용 ({idx}/{total_chunks})"
                    body_text = (
                        f"<b>{self._escape_telegram_html(chunk_label)}</b>\n"
                        f"<pre>{self._escape_telegram_html(chunk)}</pre>"
                    )
                    sent_chunk = self._telegram_send_text(
                        chat_id=chat_id,
                        text=body_text,
                        keyboard_rows=None,
                        request_max_attempts=1,
                        parse_mode="HTML",
                    )
                    sent = bool(sent or sent_chunk)
                reply_text = (
                    f"TASK 지침을 보여드렸어요. `{relative_path}` 변경 요청을 보내주시면 "
                    "코덱스가 해당 파일을 직접 수정합니다."
                )
            elif exists:
                reply_text = (
                    f"`{relative_path}` 파일은 존재하지만 현재 내용이 비어 있습니다.\n"
                    "원하시는 지침 내용을 보내주시면 코덱스가 파일을 수정해 반영합니다."
                )
            else:
                reply_text = (
                    f"현재 `{relative_path}` 파일이 없습니다.\n"
                    "`TASK 지침 추가 ...` 또는 `TASK 지침 변경 ...`처럼 요청해주시면 "
                    "해당 AGENTS.md를 생성한 뒤 바로 반영합니다."
                )
            sent_footer = self._telegram_send_text(
                chat_id=chat_id,
                text=reply_text,
                keyboard_rows=self._main_menu_keyboard_rows(),
                request_max_attempts=1,
            )
            sent = bool(sent or sent_footer)
            self._finalize_control_message_if_sent(chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent)
            return True

        if self._is_task_guide_edit_request_text(text):
            return self._forward_task_guide_edit_request(
                chat_id=chat_id,
                state=state,
                item=item,
                msg_id=msg_id,
                user_text=text,
            )

        if text == BUTTON_BOT_RENAME:
            self._clear_temp_task_seed(state)
            if not self.is_bot_worker or not self.bot_id:
                self._clear_ui_mode(state)
                reply_text = "현재 실행 환경에서는 봇 이름 변경을 지원하지 않습니다."
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
                return True

            base_name = self._resolve_bot_base_name()
            state["bot_rename_base_name"] = base_name
            self._set_ui_mode(state, UI_MODE_AWAITING_BOT_RENAME_ALIAS)
            shown_name = base_name if base_name else "(확인 실패)"
            reply_text = (
                "<b>봇 이름 변경</b>\n"
                f"현재 기본 이름: <code>{self._escape_telegram_html(shown_name)}</code>\n"
                "원하는 별칭을 입력해 주세요.\n"
                "적용 형식: <code>기존이름(별칭)</code>"
            )
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=self._main_menu_keyboard_rows(),
                request_max_attempts=1,
                parse_mode="HTML",
            )
            return True

        temp_mode_passthrough_buttons = {
            BUTTON_TASK_LIST_RECENT20,
            BUTTON_TASK_GUIDE_VIEW,
            BUTTON_BOT_RENAME,
            BUTTON_MENU_BACK,
        }
        if current_mode == UI_MODE_AWAITING_TEMP_TASK_DECISION and text not in temp_mode_passthrough_buttons:
            if text == BUTTON_TASK_NEW:
                state["pending_new_task_summary"] = self._build_new_task_carryover_summary(chat_id=chat_id, state=state)
                state["force_new_thread_once"] = True
                self._clear_selected_task_state(state)
                queued = list(state.get("queued_messages") or [])
                queued.extend(self._build_temp_task_seed_batch(chat_id=chat_id, state=state))
                state["queued_messages"] = self._dedupe_messages_by_message_id(messages=queued)
                self._clear_temp_task_seed(state)
                self._clear_ui_mode(state)
                reply_text = (
                    "새 TASK로 시작할게요.\n"
                    "방금 보낸 내용을 첫 요청으로 이어서 처리합니다."
                )
                keyboard_rows = self._main_menu_keyboard_rows()
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                )
                return True

            if text == BUTTON_TASK_RESUME:
                seed_query = str(state.get("temp_task_first_text") or "").strip()
                if not seed_query:
                    self._clear_temp_task_seed(state)
                    self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_QUERY)
                    reply_text = "원하시는 TASK를 검색하겠습니다. 검색어를 입력해주세요"
                    keyboard_rows = self._main_menu_keyboard_rows()
                    sent = self._send_control_reply(
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_text=reply_text,
                        keyboard_rows=keyboard_rows,
                        request_max_attempts=1,
                    )
                    return True

                candidates = self._search_task_candidates_for_resume(
                    chat_id=chat_id,
                    query=seed_query,
                    limit=self.task_search_llm_limit,
                )
                self._clear_temp_task_seed(state)
                if not candidates:
                    self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_QUERY)
                    reply_text = (
                        f"`{seed_query}`와 연관된 TASK를 찾지 못했습니다. "
                        "다른 키워드를 입력해 주세요."
                    )
                    keyboard_rows = self._main_menu_keyboard_rows()
                    sent = self._send_control_reply(
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_text=reply_text,
                        keyboard_rows=keyboard_rows,
                        request_max_attempts=1,
                    )
                    return True

                candidate_ids, candidate_buttons, candidate_map = self._build_resume_choice_payload(
                    rows=candidates,
                    max_count=self.task_search_llm_limit,
                )
                state["resume_choice_inline_only"] = True
                state["resume_candidates"] = candidate_ids
                state["resume_candidate_buttons"] = candidate_buttons
                state["resume_candidate_map"] = candidate_map
                self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
                query_html = self._escape_telegram_html(seed_query)
                header_text = (
                    "<b>연관 TASK 후보</b>\n"
                    f"검색어: <code>{query_html}</code>\n"
                    "<i>연관도 높은 순으로 정렬됩니다. 항목의 선택 버튼을 눌러 주세요.</i>"
                )
                reply_text = header_text
                footer_text = "원하시는 TASK의 선택 버튼을 누르면 바로 이어서 진행합니다."
                sent = self._send_task_cards_batch(
                    chat_id=chat_id,
                    rows=candidates,
                    header_text=header_text,
                    footer_text=footer_text,
                    parse_mode="HTML",
                )
                self._finalize_control_message_if_sent(chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent)
                return True

            reply_text = "새 TASK로 시작할지, 기존 TASK를 이어갈지 버튼으로 선택해 주세요."
            keyboard_rows = [[BUTTON_TASK_NEW, BUTTON_TASK_RESUME]]
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            return True

        if text == BUTTON_TASK_RESUME:
            self._clear_temp_task_seed(state)
            self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_QUERY)
            state["resume_choice_inline_only"] = False
            state["resume_candidates"] = []
            state["resume_candidate_buttons"] = []
            state["resume_candidate_map"] = {}
            reply_text = "원하시는 TASK를 검색하겠습니다. 검색어를 입력해주세요"
            keyboard_rows = self._main_menu_keyboard_rows()
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            return True

        if text == BUTTON_TASK_NEW:
            self._clear_temp_task_seed(state)
            self._set_ui_mode(state, UI_MODE_AWAITING_NEW_TASK_INPUT)
            state["resume_choice_inline_only"] = False
            state["resume_candidates"] = []
            state["resume_candidate_buttons"] = []
            state["resume_candidate_map"] = {}
            reply_text = "새 TASK로 시작할 지시를 입력해 주세요."
            keyboard_rows = self._main_menu_keyboard_rows()
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            return True

        if text == BUTTON_MENU_BACK:
            self._clear_temp_task_seed(state)
            self._clear_ui_mode(state)
            reply_text = "메뉴로 돌아왔어요."
            keyboard_rows = self._main_menu_keyboard_rows()
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            return True

        if current_mode == UI_MODE_AWAITING_RESUME_QUERY:
            candidates = self._search_task_candidates_for_resume(
                chat_id=chat_id,
                query=text,
                limit=self.task_search_llm_limit,
            )
            if not candidates:
                reply_text = f"`{text}`와 연관된 TASK를 찾지 못했습니다. 다른 키워드를 입력해 주세요."
                keyboard_rows = self._main_menu_keyboard_rows()
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                )
                return True

            candidate_ids, candidate_buttons, candidate_map = self._build_resume_choice_payload(
                rows=candidates,
                max_count=self.task_search_llm_limit,
            )
            state["resume_choice_inline_only"] = True
            state["resume_candidates"] = candidate_ids
            state["resume_candidate_buttons"] = candidate_buttons
            state["resume_candidate_map"] = candidate_map
            self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
            query_html = self._escape_telegram_html(text)
            header_text = (
                "<b>연관 TASK 후보</b>\n"
                f"검색어: <code>{query_html}</code>\n"
                "<i>연관도 높은 순으로 정렬됩니다. 항목의 선택 버튼을 눌러 주세요.</i>"
            )
            reply_text = header_text
            footer_text = "원하시는 TASK의 선택 버튼을 누르면 바로 이어서 진행합니다."
            sent = self._send_task_cards_batch(
                chat_id=chat_id,
                rows=candidates,
                header_text=header_text,
                footer_text=footer_text,
                parse_mode="HTML",
            )
            self._finalize_control_message_if_sent(chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent)
            return True

        if current_mode == UI_MODE_AWAITING_RESUME_CHOICE:
            candidate_ids = [
                _service_utils.normalize_task_id_token(v)
                for v in (state.get("resume_candidates") or [])
            ]
            candidate_ids = [v for v in candidate_ids if v]
            candidate_buttons = [_service_utils.normalize_ui_text(v) for v in (state.get("resume_candidate_buttons") or []) if _service_utils.normalize_ui_text(v)]
            candidate_map_raw = state.get("resume_candidate_map") if isinstance(state.get("resume_candidate_map"), dict) else {}
            inline_only = bool(state.get("resume_choice_inline_only"))
            if callback_selected_task_id:
                selected_task_id = callback_selected_task_id
            else:
                selected_task_id = self._resolve_task_choice(text=text, candidates=candidate_ids, candidate_map=candidate_map_raw)
            if callback_selected_task_id and candidate_ids and selected_task_id not in candidate_ids:
                reply_text = "선택 가능한 목록이 갱신되었습니다. `TASK 목록 보기(최근20)`를 다시 눌러 주세요."
                keyboard_rows = self._main_menu_keyboard_rows()
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                )
                return True
            if not selected_task_id:
                if inline_only:
                    reply_text = "목록 항목의 `선택` 버튼을 누르거나, 번호(1,2,3...) 또는 TASK ID를 입력해 주세요."
                    keyboard_rows = None
                else:
                    reply_text = "후보 버튼을 누르거나, 번호(1,2,3...)를 입력해 주세요."
                    keyboard_rows = (
                        _service_utils.build_candidate_keyboard_rows(
                            candidate_buttons,
                            main_menu_rows=self._main_menu_keyboard_rows(),
                        )
                        if candidate_buttons
                        else self._main_menu_keyboard_rows()
                    )
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                )
                return True

            row = self._load_task_row(chat_id=chat_id, task_id=selected_task_id, include_instrunction=False)
            if not row:
                reply_text = f"{selected_task_id} TASK를 찾지 못했습니다. 다시 선택해 주세요."
                keyboard_rows = None if inline_only else (
                    _service_utils.build_candidate_keyboard_rows(
                        candidate_buttons,
                        main_menu_rows=self._main_menu_keyboard_rows(),
                    )
                    if candidate_buttons
                    else self._main_menu_keyboard_rows()
                )
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                )
                return True

            self._set_selected_task_state(chat_id=chat_id, state=state, row=row)
            state["resume_recent_chat_summary_once"] = self._build_recent_chat_summary(
                chat_id=chat_id,
                hours=DEFAULT_RESUME_CHAT_SUMMARY_HOURS,
                target_lines=DEFAULT_RESUME_CHAT_SUMMARY_LINES,
                max_chars=DEFAULT_RESUME_CHAT_SUMMARY_MAX_CHARS,
                exclude_message_id=msg_id,
            )
            state["resume_context_inject_once"] = True
            if not str(state.get("active_turn_id") or "").strip():
                self._apply_selected_task_thread_target(chat_id=chat_id, state=state)
            self._clear_ui_mode(state)
            reply_text = (
                f"{selected_task_id} TASK로 이어서 진행할게요.\n"
                "이제 이어서 할 내용을 보내주시면 바로 처리합니다."
            )
            callback_source_message_id = int(item.get("callback_message_id", 0) or 0)
            keyboard_rows = self._main_menu_keyboard_rows()
            sent = self._telegram_send_text(
                chat_id=chat_id,
                text=reply_text,
                keyboard_rows=keyboard_rows,
                request_max_attempts=1,
            )
            used_fallback_edit = False
            if sent:
                self._log(
                    f"task_select_delivery=send_first chat_id={chat_id} task_id={selected_task_id}"
                )
            elif callback_selected_task_id and callback_source_message_id > 0:
                self._log(
                    "WARN: task_select_delivery send_first_failed "
                    f"chat_id={chat_id} task_id={selected_task_id} callback_message_id={callback_source_message_id}"
                )
                sent = self._telegram_edit_message_text(
                    chat_id=chat_id,
                    message_id=callback_source_message_id,
                    text=reply_text,
                    inline_keyboard_rows=[],
                    request_max_attempts=1,
                )
                used_fallback_edit = bool(sent)
                if sent:
                    self._log(
                        f"task_select_delivery=fallback_edit chat_id={chat_id} task_id={selected_task_id} callback_message_id={callback_source_message_id}"
                    )
            if sent:
                self._log(
                    f"task_select_focus_mode=no_post_edit chat_id={chat_id} task_id={selected_task_id}"
                )
            self._finalize_control_message_if_sent(chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent)
            return True

        if current_mode == UI_MODE_AWAITING_TASK_GUIDE_EDIT:
            if callback_selected_task_id:
                return False
            return self._forward_task_guide_edit_request(
                chat_id=chat_id,
                state=state,
                item=item,
                msg_id=msg_id,
                user_text=text,
            )

        if current_mode == UI_MODE_AWAITING_BOT_RENAME_ALIAS:
            if callback_selected_task_id:
                return False
            alias = self._normalize_bot_alias(text, max_len=32)
            if not alias:
                reply_text = "별칭이 비어 있습니다. 1~32자 별칭을 입력해 주세요."
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
                return True

            ok, reply_text = self._rename_bot_display_name(
                alias_text=alias,
                base_name_hint=state.get("bot_rename_base_name", ""),
            )
            if ok:
                self._clear_ui_mode(state)
            sent = self._send_control_reply(
                chat_id=chat_id,
                message_id=message_id,
                reply_text=reply_text,
                keyboard_rows=self._main_menu_keyboard_rows(),
                request_max_attempts=1,
                parse_mode="HTML",
            )
            return True

        if current_mode == UI_MODE_AWAITING_NEW_TASK_INPUT:
            state["pending_new_task_summary"] = self._build_new_task_carryover_summary(chat_id=chat_id, state=state)
            state["force_new_thread_once"] = True
            self._clear_selected_task_state(state)
            self._clear_ui_mode(state)
            if str(state.get("active_turn_id") or "").strip():
                self._telegram_send_text(
                    chat_id=chat_id,
                    text="현재 진행 중인 응답이 끝나면 새 TASK로 시작합니다.",
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
            # Do not consume this message: it must become the first instruction of the new task.
            return False

        if current_mode == UI_MODE_IDLE and not callback_selected_task_id:
            has_thread = bool(str(state.get("thread_id") or "").strip())
            has_active_turn = bool(str(state.get("active_turn_id") or "").strip())
            if not has_thread and not has_active_turn and not bool(state.get("force_new_thread_once")):
                recovered_thread_id = self._recover_latest_thread_id_for_chat(chat_id=chat_id)
                if recovered_thread_id:
                    state["thread_id"] = recovered_thread_id
                    state["app_generation"] = 0
                    self._clear_temp_task_seed(state)
                    self._save_app_server_state()
                    self._sync_app_server_session_meta(active_chat_id=chat_id)
                    self._log(
                        f"cold_start_auto_resume_thread chat_id={chat_id} thread_id={recovered_thread_id} "
                        f"msg_id={msg_id}"
                    )
                    return False

                state["temp_task_first_text"] = text
                state["temp_task_first_message_id"] = msg_id
                state["temp_task_first_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._set_ui_mode(state, UI_MODE_AWAITING_TEMP_TASK_DECISION)
                prompt_seed = self._escape_telegram_html(_service_utils.compact_prompt_text(text, max_len=120))
                reply_text = (
                    f"말씀하신 내용(<code>{prompt_seed}</code>)을 기준으로 시작할게요.\n"
                    "새 TASK로 시작할지, 기존 TASK를 이어갈지 선택해 주세요."
                )
                keyboard_rows = [[BUTTON_TASK_NEW, BUTTON_TASK_RESUME]]
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=keyboard_rows,
                    request_max_attempts=1,
                    parse_mode="HTML",
                )
                return True

        return False

    @staticmethod
    def _dedupe_messages_by_message_id(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in messages:
            if not isinstance(item, dict):
                continue
            try:
                msg_id = int(item.get("message_id"))
            except Exception:
                continue
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            deduped.append(item)
        return deduped

    def _snapshot_pending_messages(self) -> list[dict[str, object]]:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return []
        try:
            pending = telegram.get_pending_messages(str(self.store_file), include_bot=False)
        except Exception as exc:
            self._log(f"WARN: pending snapshot failed: {exc}")
            return []

        allowed_ids = set(int(v) for v in (runtime.get("allowed_user_ids") or []))
        messages: list[dict[str, object]] = []
        seen_ids: set[tuple[int, int]] = set()
        for msg in pending:
            try:
                msg_id = int(msg.get("message_id"))
                chat_id = int(msg.get("chat_id"))
                user_id = int(msg.get("user_id"))
            except Exception:
                continue
            if allowed_ids and user_id not in allowed_ids:
                continue
            dedupe_key = (chat_id, msg_id)
            if dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)
            files = msg.get("files") if isinstance(msg.get("files"), list) else []
            location = msg.get("location") if isinstance(msg.get("location"), dict) else None
            messages.append(
                {
                    "message_id": msg_id,
                    "chat_id": chat_id,
                    "text": _service_utils.compact_prompt_text(
                        _service_utils.strip_new_command_prefix(str(msg.get("text", ""))),
                        max_len=320,
                    ),
                    "files": files,
                    "location": location,
                }
            )
        messages.sort(key=lambda item: int(item.get("message_id", 0)))
        return messages

    def _task_root_for_chat(self, chat_id: int) -> Path:
        if not self.tasks_partition_by_chat:
            self.tasks_dir.mkdir(parents=True, exist_ok=True)
            return self.tasks_dir
        root = (self.tasks_dir / f"chat_{chat_id}").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _legacy_task_thread_map_path(self, chat_id: int) -> Path:
        return self._task_root_for_chat(chat_id) / LEGACY_TASK_THREAD_MAP_FILENAME

    def _load_legacy_task_thread_map(self, chat_id: int) -> dict[str, str]:
        path = self._legacy_task_thread_map_path(chat_id)
        return _service_utils.normalize_task_thread_map(_service_utils.read_json_dict(path))

    def _save_legacy_task_thread_map(self, chat_id: int, mapping: dict[str, str]) -> None:
        path = self._legacy_task_thread_map_path(chat_id)
        normalized = _service_utils.normalize_task_thread_map(mapping)
        if not _service_utils.write_json_dict_atomic(path, normalized):
            self._log(f"WARN: failed to save legacy task thread map: {path}")

    def _lookup_mapped_thread_id(self, chat_id: int, task_id: str) -> str:
        normalized_task_id = _service_utils.normalize_task_id_token(task_id)
        if not normalized_task_id:
            return ""
        mapping = self._load_legacy_task_thread_map(chat_id)
        return _service_utils.compact_prompt_text(mapping.get(normalized_task_id, ""), max_len=200)

    def _bind_task_thread_mapping(self, chat_id: int, task_id: str, thread_id: str) -> None:
        normalized_task_id = _service_utils.normalize_task_id_token(task_id)
        normalized_thread_id = _service_utils.compact_prompt_text(thread_id, max_len=200)
        if not normalized_task_id or not normalized_thread_id:
            return
        mapping = self._load_legacy_task_thread_map(chat_id)
        if mapping.get(normalized_task_id) == normalized_thread_id:
            return
        mapping[normalized_task_id] = normalized_thread_id
        self._save_legacy_task_thread_map(chat_id, mapping)

    def _task_path_hint_for_messages(self, pending_messages: list[dict[str, object]]) -> str:
        if not self.tasks_partition_by_chat:
            return "tasks/thread_{thread_id}/INSTRUNCTION.md"
        chat_ids: set[int] = set()
        for item in pending_messages:
            try:
                chat_ids.add(int(item.get("chat_id")))
            except Exception:
                continue
        if len(chat_ids) == 1:
            only_chat = next(iter(chat_ids))
            return f"tasks/chat_{only_chat}/thread_{{thread_id}}/INSTRUNCTION.md"
        return "tasks/chat_{chat_id}/thread_{thread_id}/INSTRUNCTION.md"

    def _build_dynamic_request_line(self, pending_messages: list[dict[str, object]]) -> str:
        if not pending_messages:
            rendered_refs = "없음"
            rendered_requests = "새메시지가 없습니다."
        else:
            request_entries: list[str] = []
            ref_entries: list[str] = []
            for item in pending_messages:
                msg_id = int(item.get("message_id", 0))
                text = _service_utils.compact_prompt_text(item.get("text", ""), max_len=320)
                if not text:
                    text = "(텍스트 없음, 첨부/위치 정보 참고)"
                request_entries.append(f"[msg_{msg_id}] {text}")

                files_raw = item.get("files")
                file_types: list[str] = []
                if isinstance(files_raw, list):
                    for f in files_raw:
                        if isinstance(f, dict):
                            file_type = _service_utils.compact_prompt_text(f.get("type", ""), max_len=30)
                            if file_type:
                                file_types.append(file_type)
                file_types = sorted(set(file_types))
                file_info = (
                    f"{len(files_raw)}개[{','.join(file_types)}]"
                    if isinstance(files_raw, list) and files_raw
                    else "없음"
                )

                location_info = "없음"
                location_raw = item.get("location")
                if isinstance(location_raw, dict):
                    lat = location_raw.get("latitude")
                    lon = location_raw.get("longitude")
                    if lat is not None and lon is not None:
                        location_info = f"{lat},{lon}"

                if file_info != "없음" or location_info != "없음":
                    ref_entries.append(f"msg_{msg_id}: files={file_info}, location={location_info}")

            rendered_refs = " | ".join(ref_entries) if ref_entries else "없음"
            rendered_requests = " | ".join(request_entries)
        task_path_hint = self._task_path_hint_for_messages(pending_messages)

        return (
            f"참조사항: {rendered_refs}\n"
            "작업 메모리는 sonolbot-tasks 스킬 규칙을 따를 것 "
            f"({task_path_hint} 선읽기 및 변경 즉시 동기화).\n"
            "요청사항을 처리한 후, 사용자에게 전달할 최종 답변 본문만 작성할 것 "
            "(결과에는 지침 준수/백그라운드 동작 언급 없이 요청사항에 대한 직접적인 답변만 포함할 것. "
            "친절하고 이해하기 쉽게 답하되 꼭 알아야 할 사항을 빠뜨리지 말것)\n"
            "최종 답변은 텔레그램 HTML 파싱 기준으로 작성할 것 "
            "(필요시 <b>, <code> 최소 사용, Markdown 문법은 사용하지 말 것).\n"
            f"요청사항: {rendered_requests}"
        )

    def _build_codex_prompt(self, pending_messages: list[dict[str, object]]) -> str:
        request_line = self._build_dynamic_request_line(pending_messages)
        # Keep the injected request as the very last line.
        return PROMPT_TEXT.strip() + "\n" + request_line

    def _task_prepare_batch(
        self,
        chat_id: int,
        state: dict[str, Any],
        messages: list[dict[str, Any]],
        thread_id: str,
    ) -> str:
        if not messages or not str(thread_id or "").strip():
            return ""
        task_skill = self._get_task_skill()
        if task_skill is None:
            return ""
        task_root = self._task_root_for_chat(chat_id)
        query_tokens: list[str] = []
        source_message_ids: set[int] = set()
        for item in messages:
            try:
                msg_id = int(item.get("message_id"))
            except Exception:
                continue
            if msg_id > 0:
                source_message_ids.add(msg_id)
            instruction = _service_utils.compact_prompt_text(item.get("text", ""), max_len=1200)
            if not instruction:
                instruction = "(텍스트 없음, 첨부/위치 정보 참고)"
            query_tokens.append(instruction)

        if not query_tokens:
            return ""
        lead_instruction = query_tokens[-1]
        task_id = f"thread_{thread_id}"
        try:
            session = task_skill.init_task_session(
                tasks_dir=str(task_root),
                task_id=task_id,
                thread_id=thread_id,
                instruction=lead_instruction,
                message_id=max(source_message_ids) if source_message_ids else 0,
                source_message_ids=sorted(source_message_ids),
                chat_id=chat_id,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                logs_dir=str(self.logs_dir),
            )
            task_dir = str(session.get("task_dir") or "").strip()
            if task_dir:
                task_skill.read_instrunction_first(task_dir=task_dir, logs_dir=str(self.logs_dir))
            active_task_ids: set[str] = state.get("active_task_ids") or set()
            active_task_ids.add(task_id)
            state["active_task_ids"] = active_task_ids
            selected_task_id = _service_utils.normalize_task_id_token(state.get("selected_task_id"))
            if selected_task_id:
                self._bind_task_thread_mapping(
                    chat_id=chat_id,
                    task_id=selected_task_id,
                    thread_id=thread_id,
                )
        except Exception as exc:
            self._log(f"WARN: task init/read failed chat_id={chat_id} task_id={task_id}: {exc}")
            return ""

        try:
            packet = str(
                task_skill.build_compact_memory_packet(
                    query=" | ".join(query_tokens),
                    tasks_dir=str(task_root),
                    limit=3,
                    max_chars=1000,
                    logs_dir=str(self.logs_dir),
                )
            ).strip()
        except Exception as exc:
            self._log(f"WARN: compact task memory build failed chat_id={chat_id}: {exc}")
            return ""
        if not packet or packet == "관련 TASK를 찾지 못했습니다.":
            return ""
        return packet

    def _task_record_batch_change(
        self,
        *,
        chat_id: int,
        task_ids: set[str],
        message_ids: set[int],
        status: str,
        result_text: str,
        sent_ok: bool,
    ) -> None:
        normalized_task_ids = {
            _service_utils.normalize_task_id_token(v)
            for v in (task_ids or set())
            if _service_utils.normalize_task_id_token(v)
        }
        if not normalized_task_ids:
            return
        task_skill = self._get_task_skill()
        if task_skill is None:
            return
        task_root = self._task_root_for_chat(chat_id)
        summary = _service_utils.compact_prompt_text(result_text, max_len=500)
        if status == "completed":
            if sent_ok:
                note = "app-server turn 완료 후 텔레그램 최종 답변 전송"
            else:
                note = "app-server turn 완료, 텔레그램 전송 지연으로 재시도 대기"
        else:
            note = f"app-server turn 종료(status={status})"

        for task_id in sorted(normalized_task_ids):
            try:
                task_skill.record_task_change(
                    tasks_dir=str(task_root),
                    task_id=task_id,
                    thread_id=(task_id[len("thread_") :] if task_id.startswith("thread_") else ""),
                    message_id=(max(message_ids) if message_ids else 0),
                    source_message_ids=sorted(int(v) for v in message_ids if int(v) > 0),
                    change_note=note,
                    result_summary=summary or "(응답 텍스트 없음)",
                    sent_files=[],
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    logs_dir=str(self.logs_dir),
                )
            except Exception as exc:
                self._log(f"WARN: task record failed chat_id={chat_id} task_id={task_id}: {exc}")

    def _contains_internal_agent_text(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        for pattern in INTERNAL_AGENT_TEXT_PATTERNS:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True
        return False

    def _load_latest_user_hint(self, chat_id: int, state: dict[str, Any]) -> str:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None or not hasattr(telegram, "load_message_store"):
            return ""
        try:
            store = telegram.load_message_store(str(self.store_file))
        except Exception:
            return ""
        messages = store.get("messages", [])
        if not isinstance(messages, list):
            return ""

        active_ids = {int(v) for v in (state.get("active_message_ids") or set()) if int(v) > 0}
        normalized_items: list[dict[str, Any]] = []
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            msg_type = str(raw.get("type") or "").strip().lower()
            if msg_type != "user":
                continue
            try:
                row_chat_id = int(raw.get("chat_id"))
            except Exception:
                continue
            if row_chat_id != int(chat_id):
                continue
            msg_text = _service_utils.compact_prompt_text(_service_utils.strip_new_command_prefix(str(raw.get("text", ""))), max_len=220)
            if not msg_text:
                continue
            msg_id = raw.get("message_id")
            msg_id_int = int(msg_id) if isinstance(msg_id, int) else 0
            normalized_items.append({"message_id": msg_id_int, "text": msg_text})

        if not normalized_items:
            return ""
        if active_ids:
            for row in reversed(normalized_items):
                msg_id_int = int(row.get("message_id") or 0)
                if msg_id_int > 0 and msg_id_int in active_ids:
                    return str(row.get("text") or "")
        return str(normalized_items[-1].get("text") or "")

    def _build_agent_rewriter_input(self, chat_id: int, state: dict[str, Any], raw_text: str) -> str:
        user_hint = self._load_latest_user_hint(chat_id=chat_id, state=state)
        selected_task_id = _service_utils.normalize_task_id_token(state.get("selected_task_id"))
        lines = [
            "아래 원문 안내를 지침에 맞는 사용자 진행 안내문으로 재작성하라.",
            f"- 최근 사용자 요청: {user_hint or '(없음)'}",
            f"- 선택된 TASK 식별자: {selected_task_id or '(없음)'}",
            "- 출력 형식: 텔레그램 HTML 파싱 기준(필요 시 <b>, <code>만 최소 사용, Markdown 문법 금지)",
            "- 원문 안내:",
            _service_utils.compact_prompt_text(raw_text, max_len=1200) or "(비어 있음)",
            "",
            "결과 문장만 출력하라.",
        ]
        return "\n".join(lines).strip()

    def _build_agent_rewriter_fallback(self, chat_id: int, state: dict[str, Any], raw_text: str) -> str:
        user_hint = _service_utils.compact_prompt_text(self._load_latest_user_hint(chat_id=chat_id, state=state), max_len=56)
        if not user_hint:
            raw_compact = _service_utils.compact_prompt_text(raw_text, max_len=56)
            if raw_compact and not self._contains_internal_agent_text(raw_compact):
                user_hint = raw_compact
        if user_hint:
            return (
                f"요청하신 '{user_hint}' 내용을 더 정확히 설명드리기 위해 관련 내용을 확인하고 핵심을 정리하는 중입니다. "
                "잠시만 기다려 주시면 이해하기 쉽게 이어서 안내드릴게요."
            )
        return (
            "요청하신 내용을 정확하게 설명드리기 위해 관련 내용을 확인하고 핵심을 정리하는 중입니다. "
            "잠시만 기다려 주시면 이해하기 쉽게 이어서 안내드릴게요."
        )

    def _normalize_agent_rewriter_output(self, text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        normalized = re.sub(r"^\s*(재작성 결과[:：]\s*)", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+\n", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return _service_utils.compact_prompt_text(normalized, max_len=700)

    def _rewriter_is_running(self) -> bool:
        return self.rewriter_proc is not None and self.rewriter_proc.poll() is None

    def _rewriter_send_json(self, payload: dict[str, Any]) -> bool:
        if not self._rewriter_is_running() or self.rewriter_proc is None or self.rewriter_proc.stdin is None:
            return False
        rendered = json.dumps(payload, ensure_ascii=False)
        with self.rewriter_json_send_lock:
            try:
                self.rewriter_proc.stdin.write(rendered + "\n")
                self.rewriter_proc.stdin.flush()
                self._write_agent_rewriter_log("SEND", rendered)
                return True
            except Exception as exc:
                self._log(f"WARN: agent-rewriter send failed: {exc}")
                return False

    def _rewriter_notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        return self._rewriter_send_json(payload)

    def _rewriter_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._rewriter_is_running():
            return None

        with self.rewriter_req_lock:
            req_id = self.rewriter_next_request_id
            self.rewriter_next_request_id += 1
            response_q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self.rewriter_pending_responses[req_id] = response_q

        payload: dict[str, Any] = {"id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        if not self._rewriter_send_json(payload):
            with self.rewriter_req_lock:
                self.rewriter_pending_responses.pop(req_id, None)
            return None

        wait_sec = timeout_sec if timeout_sec is not None else self.agent_rewriter_request_timeout_sec
        try:
            reply = response_q.get(timeout=max(1.0, float(wait_sec)))
        except queue.Empty:
            self._log(f"WARN: agent-rewriter request timeout method={method} id={req_id}")
            with self.rewriter_req_lock:
                self.rewriter_pending_responses.pop(req_id, None)
            return None

        if "error" in reply:
            self._log(f"WARN: agent-rewriter request error method={method} id={req_id} error={reply.get('error')}")
            return None
        result = reply.get("result")
        if isinstance(result, dict):
            return result
        return {"value": result}

    def _rewriter_handle_server_request(self, request_obj: dict[str, Any]) -> None:
        req_id = request_obj.get("id")
        method = str(request_obj.get("method") or "")
        params = request_obj.get("params")
        payload: dict[str, Any]

        if method == "item/commandExecution/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/fileChange/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/tool/requestUserInput":
            payload = {
                "id": req_id,
                "result": self._resolve_tool_user_input_answers(params if isinstance(params, dict) else {}),
            }
        elif method == "item/tool/call":
            payload = {
                "id": req_id,
                "result": {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": "dynamic tool call is not supported by this daemon bridge",
                        }
                    ],
                },
            }
        elif method == "execCommandApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        elif method == "applyPatchApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        else:
            payload = {"id": req_id, "result": {}}
            self._log(f"WARN: unhandled agent-rewriter request method={method}, replied with empty result")

        if not self._rewriter_send_json(payload):
            self._log(f"WARN: failed to send agent-rewriter request response method={method} id={req_id}")

    def _rewriter_dispatch_incoming(self, line: str) -> None:
        self._write_agent_rewriter_log("RECV", line)
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            self._log(f"WARN: non-json agent-rewriter output: {line[:180]}")
            return
        if not isinstance(obj, dict):
            return

        if "id" in obj and ("result" in obj or "error" in obj):
            req_id = obj.get("id")
            with self.rewriter_req_lock:
                pending_q = self.rewriter_pending_responses.pop(req_id, None)
            if pending_q is not None:
                try:
                    pending_q.put_nowait(obj)
                except Exception:
                    pass
            return

        method = obj.get("method")
        if not isinstance(method, str):
            return

        if "id" in obj:
            self._rewriter_handle_server_request(obj)
            return

        try:
            self.rewriter_event_queue.put_nowait(obj)
        except Exception:
            self._log("WARN: agent-rewriter event queue full; dropping event")

    def _rewriter_stdout_reader(self) -> None:
        proc = self.rewriter_proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._rewriter_dispatch_incoming(line)

    def _rewriter_stderr_reader(self) -> None:
        proc = self.rewriter_proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._write_agent_rewriter_log("ERR", line)
            if "ERROR" in line or "WARN" in line:
                self._log(f"[agent-rewriter][stderr] {line}")

    def _rewriter_process_notification(self, event: dict[str, Any]) -> None:
        method = str(event.get("method") or "")
        params = event.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "codex/event/task_complete":
            msg = params.get("msg")
            if not isinstance(msg, dict):
                return
            turn_id = str(msg.get("turn_id") or params.get("id") or "").strip()
            if not turn_id:
                return
            last_text = str(msg.get("last_agent_message") or "").strip()
            self.rewriter_turn_results[turn_id] = {
                "status": "completed",
                "text": last_text,
                "updated_at": time.time(),
            }
            return

        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                return
            turn_id = str(turn.get("id") or "").strip()
            if not turn_id:
                return
            status = str(turn.get("status") or "").strip().lower() or "completed"
            current = self.rewriter_turn_results.get(turn_id, {})
            if not isinstance(current, dict):
                current = {}
            current.setdefault("text", "")
            current["status"] = status
            current["updated_at"] = time.time()
            self.rewriter_turn_results[turn_id] = current
            return

    def _rewriter_drain_events(self, max_items: int = 200) -> None:
        for _ in range(max_items):
            try:
                event = self.rewriter_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._rewriter_process_notification(event)
            except Exception as exc:
                self._log(f"WARN: agent-rewriter event handling failed: {exc}")

    def _rewriter_wait_turn_result(self, turn_id: str, timeout_sec: float) -> dict[str, Any] | None:
        if not turn_id:
            return None
        deadline = time.time() + max(0.5, float(timeout_sec))
        while time.time() < deadline:
            self._rewriter_drain_events(max_items=200)
            current = self.rewriter_turn_results.get(turn_id)
            if isinstance(current, dict):
                status = str(current.get("status") or "").strip().lower()
                if status == "completed":
                    self.rewriter_turn_results.pop(turn_id, None)
                    return current
            if not self._rewriter_is_running():
                break
            time.sleep(0.05)
        return None

    def _stop_agent_rewriter(self, reason: str) -> None:
        if self.rewriter_proc is not None:
            self._log(f"Stopping agent-rewriter (reason={reason}, pid={self.rewriter_proc.pid})")
            try:
                self.rewriter_proc.terminate()
                self.rewriter_proc.wait(timeout=3)
            except Exception:
                try:
                    self.rewriter_proc.kill()
                except Exception:
                    pass
        self.rewriter_proc = None
        with self.rewriter_req_lock:
            self.rewriter_pending_responses.clear()
        self.rewriter_turn_results = {}
        self.rewriter_chat_threads = {}
        self._save_agent_rewriter_state()
        try:
            if self.agent_rewriter_pid_file.exists():
                self.agent_rewriter_pid_file.unlink()
        except OSError:
            pass
        self._release_agent_rewriter_lock()
        self._cleanup_agent_rewriter_workspace(reason=reason)

    def _cleanup_agent_rewriter_workspace(self, reason: str) -> None:
        if not self.agent_rewriter_cleanup_tmp:
            return
        workspace = self.agent_rewriter_workspace
        try:
            workspace_resolved = workspace.resolve()
            tmp_root_resolved = self.agent_rewriter_tmp_root.resolve()
            workspace_resolved.relative_to(tmp_root_resolved)
        except Exception:
            return
        if not workspace_resolved.exists():
            return
        try:
            shutil.rmtree(workspace_resolved)
            self._log(
                f"agent-rewriter workspace cleaned reason={reason} path={workspace_resolved}"
            )
        except OSError as exc:
            self._log(
                f"WARN: failed to clean agent-rewriter workspace "
                f"reason={reason} path={workspace_resolved}: {exc}"
            )

    def _sync_agent_rewriter_agents_file(self) -> bool:
        prompt_text = str(self.agent_rewriter_prompt or "").strip()
        if not prompt_text:
            prompt_text = DEFAULT_AGENT_REWRITER_PROMPT
        agents_path = self.agent_rewriter_workspace / REWRITER_AGENTS_FILENAME
        try:
            self.agent_rewriter_workspace.mkdir(parents=True, exist_ok=True)
            normalized = prompt_text.replace("\r\n", "\n").strip()
            agents_path.write_text(normalized + "\n", encoding="utf-8")
            self._secure_file(agents_path)
            return True
        except OSError as exc:
            self._log(f"ERROR: failed to write rewriter AGENTS.md path={agents_path}: {exc}")
            return False

    def _ensure_agent_rewriter(self) -> bool:
        if not self.agent_rewriter_enabled:
            return False
        if self._rewriter_is_running():
            return True
        if self.rewriter_proc is not None and self.rewriter_proc.poll() is not None:
            self._stop_agent_rewriter("agent_rewriter_exited")
        now_epoch = time.time()
        if (now_epoch - self.rewriter_last_restart_try_epoch) < self.agent_rewriter_restart_backoff_sec:
            return False
        self.rewriter_last_restart_try_epoch = now_epoch

        existing_pid = self._read_pid_file(self.agent_rewriter_pid_file)
        if existing_pid > 0 and (self.rewriter_proc is None or existing_pid != int(self.rewriter_proc.pid)):
            if _is_pid_alive(existing_pid):
                if self._is_codex_app_server_pid(existing_pid):
                    self._log(f"agent_rewriter_existing_pid_running pid={existing_pid}; skip duplicate start")
                    return False
                self._log(
                    f"WARN: stale rewriter pid file points to non app-server process pid={existing_pid}; clearing"
                )
            try:
                self.agent_rewriter_pid_file.unlink()
            except OSError:
                pass

        if not self._acquire_agent_rewriter_lock():
            return False

        cmd = self._build_codex_app_server_cmd(role="agent-rewriter")
        rewriter_env = self.env.copy()
        rewriter_env["SONOLBOT_AGENT_REWRITER"] = "1"
        rewriter_env["WORK_DIR"] = str(self.agent_rewriter_workspace)
        rewriter_env["SONOLBOT_ALLOWED_SKILLS"] = ""
        if not self._sync_agent_rewriter_agents_file():
            self._release_agent_rewriter_lock()
            return False
        try:
            self.rewriter_proc = subprocess.Popen(
                cmd,
                cwd=str(self.agent_rewriter_workspace),
                env=rewriter_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=(os.name != "nt"),
            )
        except Exception as exc:
            self.rewriter_proc = None
            self._release_agent_rewriter_lock()
            self._log(f"ERROR: failed to start agent-rewriter: {exc}")
            return False

        threading.Thread(target=self._rewriter_stdout_reader, daemon=True).start()
        threading.Thread(target=self._rewriter_stderr_reader, daemon=True).start()
        try:
            self.agent_rewriter_pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.agent_rewriter_pid_file.write_text(str(self.rewriter_proc.pid), encoding="utf-8")
            self._secure_file(self.agent_rewriter_pid_file)
        except OSError:
            pass

        init_result = self._rewriter_request(
            "initialize",
            {"clientInfo": {"name": "sonolbot-agent-rewriter", "version": "1.0"}, "capabilities": {}},
            timeout_sec=15.0,
        )
        if init_result is None:
            self._log("ERROR: agent-rewriter initialize failed")
            self._stop_agent_rewriter("initialize_failed")
            return False
        self._rewriter_notify("initialized")
        self._log(f"agent-rewriter started pid={self.rewriter_proc.pid} listen={self.app_server_listen}")
        return True

    def _agent_rewriter_attach_or_create_thread(self, chat_id: int) -> str:
        thread_id = str(self.rewriter_chat_threads.get(int(chat_id)) or "").strip()
        if thread_id:
            resumed = self._rewriter_request(
                "thread/resume",
                {
                    "threadId": thread_id,
                    "cwd": str(self.agent_rewriter_workspace),
                    "approvalPolicy": self.app_server_approval_policy,
                    "sandbox": self.app_server_sandbox,
                    "model": self.agent_rewriter_model,
                },
                timeout_sec=12.0,
            )
            if resumed is not None:
                return thread_id
            self.rewriter_chat_threads.pop(int(chat_id), None)
            self._save_agent_rewriter_state()

        started = self._rewriter_request(
            "thread/start",
            {
                "cwd": str(self.agent_rewriter_workspace),
                "approvalPolicy": self.app_server_approval_policy,
                "sandbox": self.app_server_sandbox,
                "model": self.agent_rewriter_model,
            },
            timeout_sec=12.0,
        )
        if started is None:
            return ""
        thread = started.get("thread")
        if not isinstance(thread, dict):
            return ""
        thread_id = str(thread.get("id") or "").strip()
        if not thread_id:
            return ""
        self.rewriter_chat_threads[int(chat_id)] = thread_id
        self._save_agent_rewriter_state()
        self._log(f"agent-rewriter thread started chat_id={chat_id} thread_id={thread_id}")
        return thread_id

    def _rewrite_agent_message(
        self,
        chat_id: int,
        state: dict[str, Any],
        raw_text: str,
        fallback_to_raw: bool = False,
    ) -> str:
        raw = str(raw_text or "").strip()
        if not raw:
            return ""
        if not self.agent_rewriter_enabled:
            return raw

        attempts = max(1, int(self.agent_rewriter_max_retry) + 1)
        for attempt in range(1, attempts + 1):
            if not self._ensure_agent_rewriter():
                continue
            thread_id = self._agent_rewriter_attach_or_create_thread(chat_id=chat_id)
            if not thread_id:
                continue

            payload = {
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": self._build_agent_rewriter_input(chat_id=chat_id, state=state, raw_text=raw),
                    }
                ],
                "model": self.agent_rewriter_model,
                "effort": self.agent_rewriter_reasoning_effort,
                "approvalPolicy": self.app_server_approval_policy,
            }
            started = self._rewriter_request("turn/start", payload, timeout_sec=self.agent_rewriter_request_timeout_sec)
            if started is None:
                continue
            turn = started.get("turn")
            turn_id = ""
            if isinstance(turn, dict):
                turn_id = str(turn.get("id") or "").strip()
            if not turn_id:
                turn_id = str(started.get("turnId") or "").strip()
            if not turn_id:
                continue

            result = self._rewriter_wait_turn_result(turn_id=turn_id, timeout_sec=self.agent_rewriter_timeout_sec)
            if not isinstance(result, dict):
                continue
            rewritten = self._normalize_agent_rewriter_output(str(result.get("text") or ""))
            if not rewritten:
                continue
            if self._contains_internal_agent_text(rewritten):
                self._log(
                    f"WARN: agent-rewriter output contained internal terms chat_id={chat_id} "
                    f"attempt={attempt}/{attempts}"
                )
                continue
            return rewritten

        if fallback_to_raw:
            return raw
        return self._build_agent_rewriter_fallback(chat_id=chat_id, state=state, raw_text=raw)

    def _app_is_running(self) -> bool:
        return self.app_proc is not None and self.app_proc.poll() is None

    def _app_send_json(self, payload: dict[str, Any]) -> bool:
        if not self._app_is_running() or self.app_proc is None or self.app_proc.stdin is None:
            return False
        rendered = json.dumps(payload, ensure_ascii=False)
        with self.app_json_send_lock:
            try:
                self.app_proc.stdin.write(rendered + "\n")
                self.app_proc.stdin.flush()
                self._write_app_server_log("SEND", rendered)
                return True
            except Exception as exc:
                self._log(f"WARN: app-server send failed: {exc}")
                return False

    def _app_notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        return self._app_send_json(payload)

    def _app_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._app_is_running():
            return None

        req_id = 0
        response_q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self.app_req_lock:
            req_id = self.app_next_request_id
            self.app_next_request_id += 1
            self.app_pending_responses[req_id] = response_q

        payload: dict[str, Any] = {"id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        if not self._app_send_json(payload):
            with self.app_req_lock:
                self.app_pending_responses.pop(req_id, None)
            return None

        wait_sec = timeout_sec if timeout_sec is not None else self.app_server_request_timeout_sec
        try:
            reply = response_q.get(timeout=max(1.0, wait_sec))
        except queue.Empty:
            self._log(f"WARN: app-server request timeout method={method} id={req_id}")
            with self.app_req_lock:
                self.app_pending_responses.pop(req_id, None)
            return None

        if "error" in reply:
            self._log(f"WARN: app-server request error method={method} id={req_id} error={reply.get('error')}")
            return None
        result = reply.get("result")
        if isinstance(result, dict):
            return result
        return {"value": result}

    def _resolve_tool_user_input_answers(self, params: dict[str, Any]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        questions = params.get("questions")
        if isinstance(questions, list):
            for q in questions:
                if not isinstance(q, dict):
                    continue
                qid = str(q.get("id") or "").strip()
                if not qid:
                    continue
                selected = ""
                opts = q.get("options")
                if isinstance(opts, list) and opts:
                    first = opts[0]
                    if isinstance(first, dict):
                        selected = str(first.get("label") or "").strip()
                    else:
                        selected = str(first).strip()
                if not selected:
                    selected = "확인"
                answers[qid] = {"answers": [selected]}
        return {"answers": answers}

    def _app_handle_server_request(self, request_obj: dict[str, Any]) -> None:
        req_id = request_obj.get("id")
        method = str(request_obj.get("method") or "")
        params = request_obj.get("params")
        payload: dict[str, Any]

        if method == "item/commandExecution/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/fileChange/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/tool/requestUserInput":
            payload = {
                "id": req_id,
                "result": self._resolve_tool_user_input_answers(params if isinstance(params, dict) else {}),
            }
        elif method == "item/tool/call":
            payload = {
                "id": req_id,
                "result": {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": "dynamic tool call is not supported by this daemon bridge",
                        }
                    ],
                },
            }
        elif method == "execCommandApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        elif method == "applyPatchApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        else:
            payload = {"id": req_id, "result": {}}
            self._log(f"WARN: unhandled app-server request method={method}, replied with empty result")

        if not self._app_send_json(payload):
            self._log(f"WARN: failed to send app-server request response method={method} id={req_id}")

    def _app_dispatch_incoming(self, line: str) -> None:
        self._write_app_server_log("RECV", line)
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            self._log(f"WARN: non-json app-server output: {line[:180]}")
            return
        if not isinstance(obj, dict):
            return

        if "id" in obj and ("result" in obj or "error" in obj):
            req_id = obj.get("id")
            with self.app_req_lock:
                pending_q = self.app_pending_responses.pop(req_id, None)
            if pending_q is not None:
                try:
                    pending_q.put_nowait(obj)
                except Exception:
                    pass
            return

        method = obj.get("method")
        if not isinstance(method, str):
            return

        # Server request (expects response).
        if "id" in obj:
            self._app_handle_server_request(obj)
            return

        try:
            self.app_event_queue.put_nowait(obj)
        except Exception:
            self._log("WARN: app-server event queue full; dropping event")

    def _app_stdout_reader(self) -> None:
        proc = self.app_proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._app_dispatch_incoming(line)

    def _app_stderr_reader(self) -> None:
        proc = self.app_proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._write_app_server_log("ERR", line)
            if "ERROR" in line or "WARN" in line:
                self._log(f"[app-server][stderr] {line}")

    def _stop_app_server(self, reason: str) -> None:
        if self.app_proc is not None:
            self._log(f"Stopping app-server (reason={reason}, pid={self.app_proc.pid})")
            try:
                self.app_proc.terminate()
                self.app_proc.wait(timeout=3)
            except Exception:
                try:
                    self.app_proc.kill()
                except Exception:
                    pass
        self.app_proc = None
        with self.app_req_lock:
            self.app_pending_responses.clear()
        self.app_turn_to_chat.clear()
        self.app_aux_turn_results = {}
        for state in self.app_chat_states.values():
            state["active_turn_id"] = ""
            state["active_message_ids"] = set()
            state["active_task_ids"] = set()
            state["delta_text"] = ""
            state["final_text"] = ""
            state["last_agent_message_sent"] = ""
            state["last_agent_message_raw"] = ""
            state["last_progress_len"] = 0
            state["last_progress_sent_at"] = 0.0
            state["last_lease_heartbeat_at"] = 0.0
        self._release_owned_chat_leases(reason=f"app_server_stop:{reason}")
        try:
            if self.codex_pid_file.exists():
                self.codex_pid_file.unlink()
        except OSError:
            pass
        self._release_app_server_lock()
        self._stop_agent_rewriter(f"app_server_stop:{reason}")
        if self.codex_run_meta and str(self.codex_run_meta.get("mode") or "").strip() == "app_server":
            self.codex_run_meta["app_server_pid"] = 0
            self.codex_run_meta["current_thread_id"] = ""
            self.codex_run_meta["thread_id"] = ""
            self.codex_run_meta["session_id"] = ""
            self._sync_app_server_session_meta()

    def _ensure_app_server(self) -> bool:
        if self._app_is_running():
            return True
        if self.app_proc is not None and self.app_proc.poll() is not None:
            self._stop_app_server("app_server_exited")
        now_epoch = time.time()
        if (now_epoch - self.app_last_restart_try_epoch) < self.app_server_restart_backoff_sec:
            return False
        self.app_last_restart_try_epoch = now_epoch

        existing_pid = self._read_pid_file(self.codex_pid_file)
        if existing_pid > 0 and (self.app_proc is None or existing_pid != int(self.app_proc.pid)):
            if _is_pid_alive(existing_pid):
                if self._is_codex_app_server_pid(existing_pid):
                    self._log(f"app_server_existing_pid_running pid={existing_pid}; skip duplicate start")
                    return False
                self._log(
                    f"WARN: stale codex pid file points to non app-server process pid={existing_pid}; clearing"
                )
            try:
                self.codex_pid_file.unlink()
            except OSError:
                pass

        if not self._acquire_app_server_lock():
            return False

        cmd = self._build_codex_app_server_cmd(role="app-server")
        try:
            self.app_proc = subprocess.Popen(
                cmd,
                cwd=str(self.codex_work_dir),
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=(os.name != "nt"),
            )
        except Exception as exc:
            self.app_proc = None
            self._release_app_server_lock()
            self._log(f"ERROR: failed to start app-server: {exc}")
            return False

        self.app_proc_generation += 1
        threading.Thread(target=self._app_stdout_reader, daemon=True).start()
        threading.Thread(target=self._app_stderr_reader, daemon=True).start()
        try:
            self.codex_pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.codex_pid_file.write_text(str(self.app_proc.pid), encoding="utf-8")
            self._secure_file(self.codex_pid_file)
        except OSError:
            pass

        init_result = self._app_request(
            "initialize",
            {"clientInfo": {"name": "sonolbot-daemon", "version": "1.0"}, "capabilities": {}},
            timeout_sec=20.0,
        )
        if init_result is None:
            self._log("ERROR: app-server initialize failed")
            self._stop_app_server("initialize_failed")
            return False
        self._app_notify("initialized")
        self.codex_cli_version = self._detect_codex_cli_version()
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-app_server"
        self.codex_run_meta = {
            "run_id": run_id,
            "mode": "app_server",
            "started_at": started_at,
            "started_epoch": time.time(),
            "codex_cli_version": self.codex_cli_version,
            "model": self.codex_model,
            "reasoning_effort": self.codex_reasoning_effort,
            "resume_target": "",
            "session_id": "",
            "session_id_kind": "thread_id_alias",
            "thread_id": "",
            "transport": "app_server",
            "listen": self.app_server_listen,
            "app_server_generation": self.app_proc_generation,
            "app_server_pid": self.app_proc.pid if self.app_proc else 0,
            "sessions": {},
            "thread_ids_by_chat": {},
        }
        self._sync_codex_runtime_env(
            run_id=run_id,
            mode="app_server",
            started_at=started_at,
            resume_target="",
            session_id="",
        )
        self._sync_app_server_session_meta()
        self._log(f"app-server started pid={self.app_proc.pid} listen={self.app_server_listen}")
        return True

    def _app_attach_or_create_thread(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        thread_id = str(state.get("thread_id") or "").strip()
        if bool(state.get("force_new_thread_once")) and thread_id:
            self.app_thread_to_chat.pop(thread_id, None)
            state["thread_id"] = ""
            thread_id = ""
            self._save_app_server_state()
        if not thread_id and not bool(state.get("force_new_thread_once")):
            recovered_thread_id = self._recover_latest_thread_id_for_chat(chat_id=chat_id)
            if recovered_thread_id:
                state["thread_id"] = recovered_thread_id
                state["app_generation"] = 0
                thread_id = recovered_thread_id
                self._save_app_server_state()
                self._sync_app_server_session_meta(active_chat_id=chat_id)
                self._log(
                    f"app-server thread recovered chat_id={chat_id} thread_id={recovered_thread_id}"
                )
        attached_generation = int(state.get("app_generation") or 0)
        needs_attach = attached_generation != self.app_proc_generation
        task_agents_instructions = self._load_task_agents_developer_instructions(chat_id=chat_id, state=state)

        if thread_id and needs_attach:
            resume_payload: dict[str, Any] = {
                "threadId": thread_id,
                "cwd": str(self.codex_work_dir),
                "approvalPolicy": self.app_server_approval_policy,
                "sandbox": self.app_server_sandbox,
                "model": self.codex_model,
            }
            if task_agents_instructions:
                resume_payload["developerInstructions"] = task_agents_instructions
            resumed = self._app_request(
                "thread/resume",
                resume_payload,
            )
            if resumed is None:
                thread_id = ""
                state["thread_id"] = ""
                self._save_app_server_state()
            else:
                state["app_generation"] = self.app_proc_generation
                self.app_thread_to_chat[thread_id] = chat_id
                self._save_app_server_state()
                self._sync_app_server_session_meta(active_chat_id=chat_id)
                return thread_id

        if not thread_id:
            start_payload: dict[str, Any] = {
                "cwd": str(self.codex_work_dir),
                "approvalPolicy": self.app_server_approval_policy,
                "sandbox": self.app_server_sandbox,
                "model": self.codex_model,
            }
            if task_agents_instructions:
                start_payload["developerInstructions"] = task_agents_instructions
            started = self._app_request(
                "thread/start",
                start_payload,
            )
            if started is None:
                return ""
            thread = started.get("thread")
            if not isinstance(thread, dict):
                return ""
            thread_id = str(thread.get("id") or "").strip()
            if not thread_id:
                return ""
            state["thread_id"] = thread_id
            state["app_generation"] = self.app_proc_generation
            self.app_thread_to_chat[thread_id] = chat_id
            self._save_app_server_state()
            self._sync_app_server_session_meta(active_chat_id=chat_id)
            self._log(f"app-server thread started chat_id={chat_id} thread_id={thread_id}")
        return thread_id

    def _group_pending_by_chat(self, messages: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for item in messages:
            try:
                chat_id = int(item.get("chat_id"))
                msg_id = int(item.get("message_id"))
            except Exception:
                continue
            normalized = dict(item)
            normalized["chat_id"] = chat_id
            normalized["message_id"] = msg_id
            grouped.setdefault(chat_id, []).append(normalized)
        for chat_id in grouped:
            grouped[chat_id].sort(key=lambda row: int(row.get("message_id", 0)))
        return grouped

    def _build_turn_text(
        self,
        messages: list[dict[str, Any]],
        steering: bool,
        task_packet: str = "",
        selected_task_packet: str = "",
        resume_recent_chat_summary: str = "",
        carryover_summary: str = "",
    ) -> str:
        parts: list[str] = []
        if steering:
            parts.append("추가 지시사항:")
        if carryover_summary:
            parts.append("이전 대화 핵심 요약:\n" + carryover_summary)
        if selected_task_packet:
            parts.append(selected_task_packet)
        if resume_recent_chat_summary:
            parts.append("현재 챗 최근 대화 요약:\n" + resume_recent_chat_summary)
        body = self._build_dynamic_request_line(messages)
        if task_packet:
            body = body + "\n\n작업 메모리 요약:\n" + task_packet
        parts.append(body)
        return "\n\n".join(part for part in parts if str(part).strip())

    def _collect_new_messages_for_chat(
        self,
        chat_id: int,
        state: dict[str, Any],
        pending_chat_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        active_ids: set[int] = state.get("active_message_ids") or set()
        queued_messages: list[dict[str, Any]] = state.get("queued_messages") or []
        queued_ids = {int(item.get("message_id")) for item in queued_messages if isinstance(item, dict)}
        failed_ids: set[int] = state.get("failed_reply_ids") or set()
        now_epoch = time.time()

        new_items: list[dict[str, Any]] = []
        for item in pending_chat_messages:
            msg_id = int(item.get("message_id", 0))
            if msg_id in active_ids or msg_id in queued_ids or msg_id in failed_ids:
                continue
            if self._is_message_recently_completed(msg_id, now_epoch=now_epoch):
                age_sec = self._recently_completed_message_age_sec(msg_id, now_epoch=now_epoch)
                if age_sec >= 0.0:
                    self._log_recently_completed_drop(chat_id, msg_id, age_sec)
                continue
            new_items.append(item)
        return new_items

    def _app_start_turn_for_chat(self, chat_id: int, batch: list[dict[str, Any]]) -> bool:
        if not batch:
            return False
        state = self._get_chat_state(chat_id)
        now_epoch = time.time()
        filtered_batch: list[dict[str, Any]] = []
        dropped_recent_count = 0
        for item in batch:
            msg_id = int(item.get("message_id", 0))
            if msg_id <= 0:
                continue
            if self._is_message_recently_completed(msg_id, now_epoch=now_epoch):
                age_sec = self._recently_completed_message_age_sec(msg_id, now_epoch=now_epoch)
                if age_sec >= 0.0:
                    self._log_recently_completed_drop(chat_id, msg_id, age_sec)
                dropped_recent_count += 1
                continue
            filtered_batch.append(item)
        if dropped_recent_count > 0:
            self._log(
                "turn_start_completed_cache_filter "
                f"chat_id={chat_id} dropped={dropped_recent_count} total={len(batch)}"
            )
        if not filtered_batch:
            return False
        batch = filtered_batch
        batch_message_ids = {
            int(item.get("message_id", 0))
            for item in batch
            if int(item.get("message_id", 0)) > 0
        }
        if not batch_message_ids:
            return False
        if not self._chat_lease_try_acquire(chat_id=chat_id, message_ids=batch_message_ids):
            self._log(f"chat_turn_start_skipped_due_to_lease chat_id={chat_id} batch={len(batch)}")
            return False

        started = False
        self._apply_selected_task_thread_target(chat_id=chat_id, state=state)
        thread_id = self._app_attach_or_create_thread(chat_id)
        if not thread_id:
            self._chat_lease_release(chat_id, reason="start_failed_thread")
            return False
        task_packet = self._task_prepare_batch(chat_id=chat_id, state=state, messages=batch, thread_id=thread_id)
        selected_task_packet = str(state.get("selected_task_packet") or "").strip()
        resume_recent_chat_summary = ""
        if bool(state.get("resume_context_inject_once")):
            resume_recent_chat_summary = str(state.get("resume_recent_chat_summary_once") or "").strip()
        carryover_summary = str(state.get("pending_new_task_summary") or "").strip()

        payload = {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": self._build_turn_text(
                        batch,
                        steering=False,
                        task_packet=task_packet,
                        selected_task_packet=selected_task_packet,
                        resume_recent_chat_summary=resume_recent_chat_summary,
                        carryover_summary=carryover_summary,
                    ),
                }
            ],
            "model": self.codex_model,
            "effort": self.codex_reasoning_effort,
            "approvalPolicy": self.app_server_approval_policy,
        }
        result = self._app_request("turn/start", payload)
        if result is None:
            self._chat_lease_release(chat_id, reason="start_failed_request")
            return False
        turn = result.get("turn")
        turn_id = ""
        if isinstance(turn, dict):
            turn_id = str(turn.get("id") or "").strip()
        if not turn_id:
            turn_id = str(result.get("turnId") or "").strip()
        if not turn_id:
            self._chat_lease_release(chat_id, reason="start_failed_missing_turn")
            return False

        state["active_turn_id"] = turn_id
        state["active_message_ids"] = batch_message_ids
        state["delta_text"] = ""
        state["final_text"] = ""
        state["last_agent_message_sent"] = ""
        state["last_agent_message_raw"] = ""
        state["last_progress_sent_at"] = 0.0
        state["last_progress_len"] = 0
        state["last_turn_started_at"] = time.time()
        state["last_lease_heartbeat_at"] = time.time()
        state["queued_messages"] = []
        state["pending_new_task_summary"] = ""
        state["resume_recent_chat_summary_once"] = ""
        state["resume_context_inject_once"] = False
        state["force_new_thread_once"] = False
        self._clear_temp_task_seed(state)
        self.app_turn_to_chat[turn_id] = chat_id
        self._chat_lease_touch(
            chat_id=chat_id,
            turn_id=turn_id,
            message_ids=batch_message_ids,
        )
        self._sync_app_server_session_meta(active_chat_id=chat_id)
        self._log(
            f"app-server turn started chat_id={chat_id} thread_id={thread_id} "
            f"turn_id={turn_id} batch={len(batch)}"
        )
        started = True
        return started

    def _app_steer_turn_for_chat(self, chat_id: int, new_items: list[dict[str, Any]]) -> bool:
        if not new_items:
            return True
        state = self._get_chat_state(chat_id)
        thread_id = str(state.get("thread_id") or "").strip()
        turn_id = str(state.get("active_turn_id") or "").strip()
        if not thread_id or not turn_id:
            return False
        task_packet = self._task_prepare_batch(chat_id=chat_id, state=state, messages=new_items, thread_id=thread_id)
        selected_task_packet = str(state.get("selected_task_packet") or "").strip()
        payload = {
            "threadId": thread_id,
            "expectedTurnId": turn_id,
            "input": [
                {
                    "type": "text",
                    "text": self._build_turn_text(
                        new_items,
                        steering=True,
                        task_packet=task_packet,
                        selected_task_packet=selected_task_packet,
                    ),
                }
            ],
        }
        result = self._app_request("turn/steer", payload, timeout_sec=20.0)
        if result is None:
            return False
        ack_turn = str(result.get("turnId") or "").strip()
        if ack_turn and ack_turn != turn_id:
            return False
        active_ids: set[int] = state.get("active_message_ids") or set()
        for item in new_items:
            try:
                active_ids.add(int(item.get("message_id")))
            except Exception:
                continue
        state["active_message_ids"] = active_ids
        self._chat_lease_touch(
            chat_id=chat_id,
            turn_id=turn_id,
            message_ids=active_ids,
        )
        self._sync_app_server_session_meta(active_chat_id=chat_id)
        self._log(f"app-server steer accepted chat_id={chat_id} turn_id={turn_id} messages={len(new_items)}")
        return True

    def _app_try_send_final_reply(self, chat_id: int, message_ids: set[int], text: str) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return False
        ordered_ids = sorted(int(v) for v in message_ids if int(v) > 0)
        if not ordered_ids:
            return False

        ok = False
        for attempt in range(1, self.fallback_send_max_attempts + 1):
            try:
                ok = bool(
                    self._telegram_send_text(
                        chat_id=chat_id,
                        text=text,
                        request_max_attempts=1,
                        keyboard_rows=self._main_menu_keyboard_rows(),
                    )
                )
            except Exception as exc:
                self._log(f"WARN: final reply send exception chat={chat_id} attempt={attempt}: {exc}")
                ok = False
            if ok:
                break
            if attempt < self.fallback_send_max_attempts:
                sleep_sec = self.fallback_send_retry_delay_sec * (
                    self.fallback_send_retry_backoff ** (attempt - 1)
                )
                time.sleep(sleep_sec)
        if not ok:
            return False

        try:
            telegram.save_bot_response(
                store_path=str(self.store_file),
                chat_id=chat_id,
                text=text,
                reply_to_message_ids=ordered_ids,
            )
        except Exception as exc:
            self._log(f"WARN: failed to save bot response chat={chat_id}: {exc}")

        try:
            changed = int(telegram.mark_messages_processed(str(self.store_file), ordered_ids))
        except Exception as exc:
            self._log(f"WARN: failed to mark processed chat={chat_id}: {exc}")
            changed = 0
        self._log(
            f"Final reply sent chat_id={chat_id} message_count={len(ordered_ids)} marked={changed}"
        )
        return True

    def _app_try_send_progress(self, chat_id: int, state: dict[str, Any]) -> None:
        if self.app_server_forward_agent_message:
            # Progress snippet mode is disabled when forwarding raw agent_message stream.
            return
        turn_id = str(state.get("active_turn_id") or "").strip()
        if not turn_id:
            return
        delta_text = str(state.get("delta_text") or "")
        if not delta_text.strip():
            return
        now_epoch = time.time()
        last_sent = float(state.get("last_progress_sent_at") or 0.0)
        if (now_epoch - last_sent) < self.app_server_progress_interval_sec:
            return
        last_len = int(state.get("last_progress_len") or 0)
        if len(delta_text) <= last_len:
            return
        active_ids: set[int] = state.get("active_message_ids") or set()
        if not active_ids:
            return
        active_task_ids: set[str] = state.get("active_task_ids") or set()
        if active_task_ids:
            task_prefix = sorted(active_task_ids)[0]
        else:
            thread_id = str(state.get("thread_id") or "").strip()
            if thread_id:
                task_prefix = f"thread_{thread_id}"
            else:
                task_prefix = f"msg_{min(active_ids)}"
        snippet = delta_text[-220:].strip()
        progress_text = f"[진행중] {task_prefix}\n{snippet}"

        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return
        try:
            ok = bool(
                self._telegram_send_text(
                    chat_id=chat_id,
                    text=progress_text,
                    request_max_attempts=1,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                )
            )
        except Exception as exc:
            self._log(f"WARN: progress send failed chat_id={chat_id}: {exc}")
            ok = False
        if ok:
            state["last_progress_sent_at"] = now_epoch
            state["last_progress_len"] = len(delta_text)

    def _app_try_send_agent_message(self, chat_id: int, text: str) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return False
        try:
            return bool(
                self._telegram_send_text(
                    chat_id=chat_id,
                    text=text,
                    request_max_attempts=1,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                )
            )
        except Exception as exc:
            self._log(f"WARN: intermediate agent_message send failed chat_id={chat_id}: {exc}")
            return False

    def _app_finalize_reply_without_resend(self, chat_id: int, message_ids: set[int], text: str) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return False
        ordered_ids = sorted(int(v) for v in message_ids if int(v) > 0)
        if not ordered_ids:
            return False

        try:
            telegram.save_bot_response(
                store_path=str(self.store_file),
                chat_id=chat_id,
                text=text,
                reply_to_message_ids=ordered_ids,
            )
        except Exception as exc:
            self._log(f"WARN: failed to save streamed bot response chat={chat_id}: {exc}")

        try:
            changed = int(telegram.mark_messages_processed(str(self.store_file), ordered_ids))
        except Exception as exc:
            self._log(f"WARN: failed to mark streamed reply processed chat={chat_id}: {exc}")
            return False
        self._log(
            f"Final reply already streamed chat_id={chat_id} message_count={len(ordered_ids)} marked={changed}"
        )
        return True

    def _app_on_turn_completed(self, thread_id: str, turn: dict[str, Any]) -> None:
        chat_id = self.app_thread_to_chat.get(thread_id)
        if chat_id is None:
            return
        state = self._get_chat_state(chat_id)
        turn_id = str(turn.get("id") or "").strip()
        if turn_id and str(state.get("active_turn_id") or "").strip() and turn_id != str(state.get("active_turn_id")):
            self._log(f"WARN: completed turn mismatch chat_id={chat_id} completed={turn_id} active={state.get('active_turn_id')}")

        status = str(turn.get("status") or "").strip().lower() or "completed"
        final_text = str(state.get("final_text") or "").strip()
        message_ids: set[int] = set(state.get("active_message_ids") or set())
        task_ids: set[str] = set(state.get("active_task_ids") or set())
        if not task_ids and thread_id:
            task_ids = {f"thread_{thread_id}"}
        last_agent_message_sent = str(state.get("last_agent_message_sent") or "")

        sent_ok = False
        if status == "completed" and final_text and message_ids:
            if last_agent_message_sent and last_agent_message_sent == final_text:
                sent_ok = self._app_finalize_reply_without_resend(
                    chat_id=chat_id,
                    message_ids=message_ids,
                    text=final_text,
                )
            else:
                sent_ok = self._app_try_send_final_reply(chat_id=chat_id, message_ids=message_ids, text=final_text)
            if not sent_ok:
                state["failed_reply_text"] = final_text
                state["failed_reply_ids"] = set(message_ids)
                self._log(
                    f"WARN: final reply send deferred chat_id={chat_id} "
                    f"messages={len(message_ids)}"
                )
            else:
                state["failed_reply_text"] = ""
                state["failed_reply_ids"] = set()
        elif status == "completed" and not final_text and message_ids:
            self._log(
                f"WARN: turn completed without task_complete final message chat_id={chat_id} "
                f"messages={len(message_ids)}"
            )
        elif status != "completed":
            self._log(f"WARN: turn completed with non-success status chat_id={chat_id} status={status}")

        self._task_record_batch_change(
            chat_id=chat_id,
            task_ids=task_ids,
            message_ids=message_ids,
            status=status,
            result_text=final_text,
            sent_ok=sent_ok,
        )
        selected_task_id = _service_utils.normalize_task_id_token(state.get("selected_task_id"))
        if selected_task_id and thread_id:
            self._bind_task_thread_mapping(
                chat_id=chat_id,
                task_id=selected_task_id,
                thread_id=thread_id,
            )
        if status == "completed" and message_ids:
            self._remember_completed_message_ids(message_ids)
        self._chat_lease_release(chat_id, reason=f"turn_completed:{status or 'completed'}")

        state["active_turn_id"] = ""
        state["active_message_ids"] = set()
        state["active_task_ids"] = set()
        state["delta_text"] = ""
        state["final_text"] = ""
        state["last_agent_message_sent"] = ""
        state["last_agent_message_raw"] = ""
        state["last_progress_len"] = 0
        state["last_progress_sent_at"] = 0.0
        state["last_lease_heartbeat_at"] = 0.0
        if turn_id:
            self.app_turn_to_chat.pop(turn_id, None)
        self._sync_app_server_session_meta(active_chat_id=chat_id)

    def _app_process_notification(self, event: dict[str, Any]) -> None:
        method = str(event.get("method") or "")
        params = event.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "turn/started":
            thread_id = str(params.get("threadId") or "").strip()
            turn = params.get("turn")
            if not isinstance(turn, dict):
                return
            turn_id = str(turn.get("id") or "").strip()
            chat_id = self.app_thread_to_chat.get(thread_id)
            if chat_id is None:
                return
            state = self._get_chat_state(chat_id)
            if turn_id:
                state["active_turn_id"] = turn_id
                self.app_turn_to_chat[turn_id] = chat_id
                state["last_turn_started_at"] = time.time()
                state["last_lease_heartbeat_at"] = time.time()
                self._chat_lease_touch(
                    chat_id=chat_id,
                    turn_id=turn_id,
                    message_ids=set(state.get("active_message_ids") or set()),
                )
                self._sync_app_server_session_meta(active_chat_id=chat_id)
            return

        if method == "item/agentMessage/delta":
            thread_id = str(params.get("threadId") or "").strip()
            chat_id = self.app_thread_to_chat.get(thread_id)
            if chat_id is None:
                return
            delta = str(params.get("delta") or "")
            if not delta:
                return
            state = self._get_chat_state(chat_id)
            state["delta_text"] = str(state.get("delta_text") or "") + delta
            return

        if method == "item/completed":
            item = params.get("item")
            if not isinstance(item, dict):
                return
            item_type = str(item.get("type") or "").strip().lower()
            if item_type != "agentmessage":
                return
            return

        if method == "codex/event/agent_message":
            if not self.app_server_forward_agent_message:
                return
            msg = params.get("msg")
            if not isinstance(msg, dict):
                return
            raw_message_text = str(msg.get("message") or "")
            if not raw_message_text.strip():
                return
            thread_id = str(params.get("conversationId") or "").strip()
            if not thread_id:
                thread_id = str(msg.get("thread_id") or "").strip()
            chat_id = self.app_thread_to_chat.get(thread_id)
            if chat_id is None:
                turn_id = str(params.get("id") or "").strip()
                if turn_id:
                    chat_id = self.app_turn_to_chat.get(turn_id)
            if chat_id is None:
                return
            state = self._get_chat_state(chat_id)
            if str(state.get("last_agent_message_raw") or "") == raw_message_text:
                return
            message_text = self._rewrite_agent_message(
                chat_id=chat_id,
                state=state,
                raw_text=raw_message_text,
                fallback_to_raw=False,
            )
            if not str(message_text or "").strip():
                return
            sent = self._app_try_send_agent_message(chat_id=chat_id, text=message_text)
            if sent:
                state["last_agent_message_raw"] = raw_message_text
                state["last_agent_message_sent"] = message_text
            return

        if method == "codex/event/task_complete":
            msg = params.get("msg")
            if not isinstance(msg, dict):
                return
            raw_final_text = str(msg.get("last_agent_message") or "").strip()
            if not raw_final_text:
                return
            turn_id = str(msg.get("turn_id") or params.get("id") or "").strip()
            if turn_id:
                aux_state = self.app_aux_turn_results.get(turn_id)
                if isinstance(aux_state, dict):
                    aux_state["status"] = "completed"
                    aux_state["text"] = raw_final_text
                    aux_state["updated_at"] = time.time()
                    self.app_aux_turn_results[turn_id] = aux_state
                    return
            thread_id = str(params.get("conversationId") or "").strip()
            if not thread_id:
                thread_id = str(msg.get("thread_id") or "").strip()
            chat_id = self.app_thread_to_chat.get(thread_id)
            if chat_id is None:
                if turn_id:
                    chat_id = self.app_turn_to_chat.get(turn_id)
            if chat_id is None:
                return
            state = self._get_chat_state(chat_id)
            state["final_text"] = raw_final_text
            return

        if method == "turn/completed":
            thread_id = str(params.get("threadId") or "").strip()
            turn = params.get("turn")
            if not isinstance(turn, dict):
                return
            aux_turn_id = str(turn.get("id") or "").strip()
            if aux_turn_id:
                aux_state = self.app_aux_turn_results.get(aux_turn_id)
                if isinstance(aux_state, dict):
                    aux_state["status"] = str(turn.get("status") or "").strip().lower() or "completed"
                    aux_state["updated_at"] = time.time()
                    self.app_aux_turn_results[aux_turn_id] = aux_state
                    return
            self._app_on_turn_completed(thread_id, turn)
            return

    def _app_drain_events(self, max_items: int = 400) -> None:
        for _ in range(max_items):
            try:
                event = self.app_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._app_process_notification(event)
            except Exception as exc:
                self._log(f"WARN: app-server event handling failed: {exc}")

    def _app_retry_failed_replies(self) -> None:
        for chat_id, state in self.app_chat_states.items():
            failed_text = str(state.get("failed_reply_text") or "").strip()
            failed_ids: set[int] = state.get("failed_reply_ids") or set()
            if not failed_text or not failed_ids:
                continue
            ok = self._app_try_send_final_reply(chat_id=chat_id, message_ids=failed_ids, text=failed_text)
            if ok:
                thread_id = str(state.get("thread_id") or "").strip()
                retry_task_ids: set[str] = {f"thread_{thread_id}"} if thread_id else set()
                self._task_record_batch_change(
                    chat_id=chat_id,
                    task_ids=retry_task_ids,
                    message_ids=set(failed_ids),
                    status="completed",
                    result_text=failed_text,
                    sent_ok=True,
                )
                state["failed_reply_text"] = ""
                state["failed_reply_ids"] = set()

    def _app_process_cycle(self) -> None:
        self._prune_completed_message_cache()
        pending_messages = self._snapshot_pending_messages()
        has_stateful_work = self._has_app_stateful_work()
        if not pending_messages and not has_stateful_work and not self._app_is_running():
            return

        if not pending_messages and not has_stateful_work and self._app_is_running():
            if self._is_bot_workspace_idle():
                if self._has_any_active_chat_lease():
                    self._log("idle_shutdown_skipped_active_lease")
                else:
                    self._stop_app_server(f"workspace_idle>{self.idle_timeout_sec}s")
            return

        if self.agent_rewriter_enabled:
            self._ensure_agent_rewriter()
        if not self._ensure_app_server():
            return
        self._app_drain_events()
        self._app_retry_failed_replies()
        # turn/completed 처리에서 processed 마킹이 반영될 수 있으므로
        # pending 스냅샷을 갱신해 같은 메시지의 동일 사이클 재투입을 방지한다.
        pending_messages = self._snapshot_pending_messages()

        grouped = self._group_pending_by_chat(pending_messages)
        chat_ids = set(grouped.keys())
        for chat_id, state in self.app_chat_states.items():
            if (
                str(state.get("active_turn_id") or "").strip()
                or state.get("queued_messages")
                or str(state.get("failed_reply_text") or "").strip()
            ):
                chat_ids.add(chat_id)

        for chat_id in sorted(chat_ids):
            pending_chat_messages = grouped.get(chat_id, [])
            state = self._get_chat_state(chat_id)
            pending_chat_messages = self._process_chat_control_messages(
                chat_id=chat_id,
                state=state,
                pending_chat_messages=pending_chat_messages,
            )
            # Turn timeout guard.
            active_turn = str(state.get("active_turn_id") or "").strip()
            if active_turn:
                started_epoch = float(state.get("last_turn_started_at") or 0.0)
                if started_epoch > 0 and (time.time() - started_epoch) > self.app_server_turn_timeout_sec:
                    thread_id = str(state.get("thread_id") or "").strip()
                    if thread_id:
                        self._log(
                            f"WARN: interrupting stale turn chat_id={chat_id} turn_id={active_turn} "
                            f"timeout={self.app_server_turn_timeout_sec}s"
                        )
                        self._app_request(
                            "turn/interrupt",
                            {"threadId": thread_id, "turnId": active_turn},
                            timeout_sec=10.0,
                        )
                    state["active_turn_id"] = ""
                    state["active_message_ids"] = set()
                    state["active_task_ids"] = set()
                    state["delta_text"] = ""
                    state["final_text"] = ""
                    state["last_agent_message_sent"] = ""
                    state["last_agent_message_raw"] = ""
                    state["last_lease_heartbeat_at"] = 0.0
                    self._chat_lease_release(chat_id, reason="turn_timeout_interrupt")
                    self._sync_app_server_session_meta(active_chat_id=chat_id)
                    active_turn = ""

            new_items = self._collect_new_messages_for_chat(chat_id, state, pending_chat_messages)
            if str(state.get("active_turn_id") or "").strip():
                last_lease_heartbeat = float(state.get("last_lease_heartbeat_at") or 0.0)
                if (time.time() - last_lease_heartbeat) >= float(self.chat_lease_heartbeat_sec):
                    touched = self._chat_lease_touch(
                        chat_id=chat_id,
                        turn_id=str(state.get("active_turn_id") or ""),
                        message_ids=set(state.get("active_message_ids") or set()),
                    )
                    if touched:
                        state["last_lease_heartbeat_at"] = time.time()
                if not new_items:
                    self._app_try_send_progress(chat_id, state)
                    continue
                if bool(state.get("force_new_thread_once")):
                    queued = list(state.get("queued_messages") or [])
                    queued.extend(new_items)
                    state["queued_messages"] = self._dedupe_messages_by_message_id(messages=queued)
                    self._app_try_send_progress(chat_id, state)
                    continue
                # Small coalescing window before steer to reduce call count.
                time.sleep(self.app_server_steer_batch_window_ms / 1000.0)
                steer_ok = self._app_steer_turn_for_chat(chat_id, new_items)
                if not steer_ok:
                    queued = list(state.get("queued_messages") or [])
                    queued.extend(new_items)
                    # de-duplicate queued rows by message id while keeping order.
                    state["queued_messages"] = self._dedupe_messages_by_message_id(messages=queued)
                self._app_try_send_progress(chat_id, state)
                continue

            batch = list(state.get("queued_messages") or [])
            if not batch and not new_items:
                continue
            if not batch:
                batch = new_items
            else:
                merged = batch + new_items
                batch = self._dedupe_messages_by_message_id(messages=merged)

            started = self._app_start_turn_for_chat(chat_id, batch)
            if not started:
                now_epoch = time.time()
                retry_batch: list[dict[str, Any]] = []
                for item in batch:
                    msg_id = int(item.get("message_id", 0))
                    if msg_id <= 0:
                        continue
                    if self._is_message_recently_completed(msg_id, now_epoch=now_epoch):
                        age_sec = self._recently_completed_message_age_sec(msg_id, now_epoch=now_epoch)
                        if age_sec >= 0.0:
                            self._log_recently_completed_drop(chat_id, msg_id, age_sec)
                        continue
                    retry_batch.append(item)
                state["queued_messages"] = retry_batch
            else:
                state["queued_messages"] = []

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self._log(f"Signal received: {signum}")
        self.stop_requested = True

    def _has_app_stateful_work(self) -> bool:
        return any(
            bool(str(state.get("active_turn_id") or "").strip())
            or bool(state.get("queued_messages"))
            or bool(str(state.get("failed_reply_text") or "").strip())
            for state in self.app_chat_states.values()
        )

    def _workspace_latest_mtime(self) -> float:
        results_dir = Path(
            os.getenv("SONOLBOT_RESULTS_DIR", str(self.bot_workspace / "results"))
        ).resolve()
        roots = [
            self.tasks_dir,
            self.app_server_state_file,
            self.app_server_log_file,
            self.codex_session_meta_file,
            self.activity_file,
            results_dir,
        ]

        latest = 0.0
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            if not root.exists():
                continue
            try:
                latest = max(latest, root.stat().st_mtime)
            except OSError:
                continue
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.is_file() and path.parent == self.logs_dir and path.name.startswith("daemon-"):
                        # Exclude daemon heartbeat logs from idle detector.
                        continue
                    if path == self.store_file or path.name == "telegram_messages.json":
                        # Telegram store can be rewritten by periodic polling even with no real work.
                        continue
                    try:
                        latest = max(latest, path.stat().st_mtime)
                    except OSError:
                        continue
        return latest

    def _is_bot_workspace_idle(self) -> bool:
        latest = self._workspace_latest_mtime()
        if latest <= 0:
            return False
        idle_sec = time.time() - latest
        return idle_sec >= float(self.idle_timeout_sec)

    def _run_doc_runtime_check(self) -> None:
        checker_path = self.root / "src" / "sonolbot" / "tools" / "check_docs_alignment.py"
        if not checker_path.exists():
            self._log(f"WARN: docs alignment checker missing: {checker_path}")
            return
        try:
            proc = subprocess.run(
                [self.python_bin, "-m", "sonolbot.tools.check_docs_alignment"],
                cwd=str(self.root),
                env=self.env,
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except Exception as exc:
            self._log(f"WARN: docs alignment checker execution failed: {exc}")
            return
        if proc.returncode == 0:
            return
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if stdout:
            for line in stdout.splitlines():
                self._log(f"[docs-check] {line}")
        if stderr:
            for line in stderr.splitlines():
                self._log(f"[docs-check][stderr] {line}")

    def _run_main_cycle(self) -> int:
        self._cleanup_logs()
        self._cleanup_activity_logs()
        self._rotate_activity_log_if_needed(force=False)
        rc = self._run_quick_check()
        if rc not in (0, 1):
            self._log(f"quick_check failed rc={rc}")
            return rc

        self._app_process_cycle()
        return rc

    def drain_pending_once(self, max_cycles: int = 120, sleep_sec: float = 1.0, use_lock: bool = True) -> int:
        if not shutil.which("codex"):
            self._log("ERROR: codex CLI not found in PATH")
            return 1

        locked = False
        if use_lock:
            try:
                self._acquire_lock()
                locked = True
            except Exception as exc:
                self._log(f"ERROR: cannot acquire daemon lock for drain mode: {exc}")
                return 1

        try:
            self._run_doc_runtime_check()
            cycles = max(1, int(max_cycles))
            pause = max(0.2, float(sleep_sec))
            for _ in range(cycles):
                rc = self._run_main_cycle()
                if rc not in (0, 1):
                    return rc

                pending = bool(self._snapshot_pending_messages())
                stateful = self._has_app_stateful_work()
                if not pending and not stateful:
                    return 0

                time.sleep(pause)

            self._log(f"WARN: drain mode reached max_cycles={cycles} before idle")
            return 1
        finally:
            self._stop_app_server("drain_mode_done")
            if locked:
                self._release_lock()

    def run(self) -> int:
        if not shutil.which("codex"):
            self._log("ERROR: codex CLI not found in PATH")
            return 1

        signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._handle_signal)

        try:
            self._acquire_lock()
        except Exception as exc:
            self._log(f"ERROR: {exc}")
            return 1
        self._log(
            "Daemon started "
            f"pid={os.getpid()} poll={self.poll_interval_sec}s idle_timeout={self.idle_timeout_sec}s "
            f"worker={self.is_bot_worker} bot_id={self.bot_id or '-'} "
            f"gui_session={self._has_gui_session()} "
            f"transport={DEFAULT_CODEX_TRANSPORT_MODE} "
            f"forward_agent_message={self.app_server_forward_agent_message} "
            f"telegram_parse_mode={self.telegram_default_parse_mode} "
            f"telegram_force_parse={self.telegram_force_parse_mode} "
            f"telegram_parse_fallback_raw={self.telegram_parse_fallback_raw_on_fail} "
            f"codex_model={self.codex_model} reasoning={self.codex_reasoning_effort} "
            f"rewriter_enabled={self.agent_rewriter_enabled} "
            f"rewriter_model={self.agent_rewriter_model} "
            f"rewriter_reasoning={self.agent_rewriter_reasoning_effort} "
            f"rewriter_workspace={self.agent_rewriter_workspace} "
            f"rewriter_prompt_file={self.agent_rewriter_prompt_file or '-'} "
            f"rewriter_cleanup_tmp={self.agent_rewriter_cleanup_tmp} "
            f"activity_max={self.activity_max_bytes} activity_backups={self.activity_backup_count} "
            f"activity_retention={self.activity_retention_days}d "
            f"tasks_partition_by_chat={self.tasks_partition_by_chat}"
        )
        self._run_doc_runtime_check()

        try:
            while not self.stop_requested:
                self._run_main_cycle()
                time.sleep(max(1, self.poll_interval_sec))
        finally:
            self._stop_app_server("daemon_shutdown")
            self._release_lock()
            self._log("Daemon stopped")
        return 0






