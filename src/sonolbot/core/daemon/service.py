"Daemon service orchestration."
from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.service_config import DaemonServiceConfig
from sonolbot.core.daemon.service_task import DaemonServiceTaskMixin, DaemonServiceTaskRuntime
from sonolbot.core.daemon.service_app import DaemonServiceAppMixin, DaemonServiceAppRuntime
from sonolbot.core.daemon.service_lease import DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime
from sonolbot.core.daemon.service_rewriter import DaemonServiceRewriterMixin
from sonolbot.core.daemon.service_telegram import DaemonServiceTelegramMixin

class DaemonService(
    DaemonServiceTaskMixin,
    DaemonServiceAppMixin,
    DaemonServiceLeaseMixin,
    DaemonServiceRewriterMixin,
    DaemonServiceTelegramMixin,
):
    def __init__(
        self,
        *,
        task_runtime: DaemonServiceTaskRuntime | None = None,
        app_runtime: DaemonServiceAppRuntime | None = None,
        lease_runtime: DaemonServiceLeaseRuntime | None = None,
        rewriter_runtime: DaemonServiceRewriterRuntime | None = None,
    ) -> None:
        self.config, init_warnings = DaemonServiceConfig.from_env()
        for name, value in self.config.as_dict().items():
            setattr(self, name, value)
        self.python_bin = self._detect_python_bin()
        self.codex_run_meta: Optional[dict[str, object]] = None
        self._telegram_runtime: Optional[dict[str, object]] = None
        self._telegram_skill = None
        self.stop_requested = False

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
        self._init_task_runtime(task_runtime)
        self._init_app_runtime(app_runtime)
        self._init_lease_runtime(lease_runtime)
        self._harden_sensitive_permissions()
        self._init_rewriter_runtime(rewriter_runtime)
        self._cleanup_activity_logs()
        self._rotate_activity_log_if_needed(force=False)

    def _detect_python_bin(self) -> str:
        venv_py = self.root / ".venv" / "bin" / "python"
        if venv_py.exists():
            return str(venv_py)
        return sys.executable

    def _daily_log_path(self) -> Path:
        return self.logs_dir / f"daemon-{datetime.now().strftime('%Y-%m-%d')}.log"

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

    def _lookup_mapped_thread_id(self, chat_id: int, task_id: str) -> str:
        normalized_task_id = _service_utils.normalize_task_id_token(task_id)
        if not normalized_task_id:
            return ""
        mapping = self._load_legacy_task_thread_map(chat_id)
        return _service_utils.compact_prompt_text(mapping.get(normalized_task_id, ""), max_len=200)

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






