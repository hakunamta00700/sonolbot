from __future__ import annotations

from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.runtime_shared import *

class DaemonServiceTaskRuntime:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.task_skill: Any = None


class DaemonServiceTaskMixin:
    def _init_task_runtime(self, task_runtime: DaemonServiceTaskRuntime | None = None) -> None:
        if task_runtime is not None and not isinstance(task_runtime, DaemonServiceTaskRuntime):
            raise TypeError("task_runtime must be DaemonServiceTaskRuntime")
        runtime: DaemonServiceTaskRuntime
        if task_runtime is None:
            runtime = DaemonServiceTaskRuntime(self)
        else:
            runtime = task_runtime
        self._task_runtime_component = runtime

    def _get_task_runtime(self) -> DaemonServiceTaskRuntime | None:
        runtime = getattr(self, "_task_runtime_component", None)
        if isinstance(runtime, DaemonServiceTaskRuntime):
            return runtime
        return None

    def _get_task_skill(self) -> object | None:
        runtime = self._get_task_runtime()
        if runtime is None:
            return None
        if runtime.task_skill is not None:
            return runtime.task_skill
        try:
            skill = get_task_skill()
        except Exception as exc:
            self._log(f"WARN: task skill init failed: {exc}")
            return None
        runtime.task_skill = skill
        return runtime.task_skill

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
    def _task_root_for_chat(self, chat_id: int) -> Path:
        if not self.tasks_partition_by_chat:
            self.tasks_dir.mkdir(parents=True, exist_ok=True)
            return self.tasks_dir
        root = (self.tasks_dir / f"chat_{chat_id}").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

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

    def _resolve_task_agents_thread_id(self, state: dict[str, Any]) -> str:
        current_thread_id = _service_utils.normalize_thread_id_token(state.get("thread_id"))
        if current_thread_id:
            return current_thread_id
        return _service_utils.normalize_thread_id_token(state.get("resume_target_thread_id"))

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

