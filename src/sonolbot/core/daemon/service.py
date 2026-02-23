"Daemon service orchestration."

from __future__ import annotations

from typing import Callable

from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.runtime_shared import (
    _ComponentLogger,
    make_component_logger,
)
from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon.service_app import (
    DaemonServiceAppMixin,
    DaemonServiceAppRuntime,
)
from sonolbot.core.daemon.service_config import DaemonServiceConfig
from sonolbot.core.daemon.service_core import (
    DaemonServiceCoreEnvPolicy,
    DaemonServiceCoreMixin,
    DaemonServiceCorePythonPolicy,
    DaemonServiceCoreRuntime,
)
from sonolbot.core.daemon.service_lease import (
    DaemonServiceLeaseMixin,
    DaemonServiceLeaseRuntime,
)
from sonolbot.core.daemon.service_rewriter import (
    DaemonServiceRewriterMixin,
    DaemonServiceRewriterRuntime,
)
from sonolbot.core.daemon.service_task import (
    DaemonServiceTaskMixin,
    DaemonServiceTaskRuntime,
)
from sonolbot.core.daemon.service_telegram import (
    DaemonServiceTelegramMixin,
    DaemonServiceTelegramRuntime,
)


class DaemonService(
    DaemonServiceCoreMixin,
    DaemonServiceTaskMixin,
    DaemonServiceAppMixin,
    DaemonServiceLeaseMixin,
    DaemonServiceRewriterMixin,
    DaemonServiceTelegramMixin,
):
    logger: _ComponentLogger
    logs_dir: Path
    tasks_dir: Path
    store_file: Path
    codex_work_dir: Path
    state_dir: Path
    chat_locks_dir: Path
    agent_rewriter_workspace: Path

    def __init__(
        self,
        *,
        core_runtime: DaemonServiceCoreRuntime | None = None,
        core_env_policy: DaemonServiceCoreEnvPolicy | None = None,
        core_python_policy: DaemonServiceCorePythonPolicy | None = None,
        service_config: DaemonServiceConfig | None = None,
        service_init_warnings: list[str] | None = None,
        logger: _ComponentLogger | None = None,
        service_config_loader: (
            Callable[[], tuple[DaemonServiceConfig, list[str]]] | None
        ) = None,
        task_runtime: DaemonServiceTaskRuntime | None = None,
        app_runtime: DaemonServiceAppRuntime | None = None,
        lease_runtime: DaemonServiceLeaseRuntime | None = None,
        telegram_runtime: DaemonServiceTelegramRuntime | None = None,
        rewriter_runtime: DaemonServiceRewriterRuntime | None = None,
    ) -> None:
        if core_runtime is not None and not isinstance(
            core_runtime, DaemonServiceCoreRuntime
        ):
            raise TypeError("core_runtime must be DaemonServiceCoreRuntime")
        if task_runtime is not None and not isinstance(
            task_runtime, DaemonServiceTaskRuntime
        ):
            raise TypeError("task_runtime must be DaemonServiceTaskRuntime")
        if app_runtime is not None and not isinstance(
            app_runtime, DaemonServiceAppRuntime
        ):
            raise TypeError("app_runtime must be DaemonServiceAppRuntime")
        if lease_runtime is not None and not isinstance(
            lease_runtime, DaemonServiceLeaseRuntime
        ):
            raise TypeError("lease_runtime must be DaemonServiceLeaseRuntime")
        if telegram_runtime is not None and not isinstance(
            telegram_runtime, DaemonServiceTelegramRuntime
        ):
            raise TypeError("telegram_runtime must be DaemonServiceTelegramRuntime")
        if rewriter_runtime is not None and not isinstance(
            rewriter_runtime, DaemonServiceRewriterRuntime
        ):
            raise TypeError("rewriter_runtime must be DaemonServiceRewriterRuntime")
        if service_config is None:
            if service_config_loader is None:
                self.config, init_warnings = DaemonServiceConfig.from_env()
            else:
                loaded, init_warnings = service_config_loader()
                if not hasattr(loaded, "as_dict"):
                    raise TypeError(
                        "service_config_loader must return (DaemonServiceConfig, list[str])"
                    )
                self.config = loaded
        else:
            self.config = service_config
            init_warnings = list(service_init_warnings or [])
        for name, value in self.config.as_dict().items():
            setattr(self, name, value)
        self.logger = (
            logger
            if logger is not None
            else make_component_logger(
                log_path=self._daily_log_path,
                component="service",
            )
        )
        self._init_core_runtime(
            core_runtime, env_policy=core_env_policy, python_policy=core_python_policy
        )
        for message in init_warnings:
            self.logger.warning(f"{message}")

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.touch(exist_ok=True)
        self.codex_work_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.chat_locks_dir.mkdir(parents=True, exist_ok=True)
        self.agent_rewriter_workspace.mkdir(parents=True, exist_ok=True)
        self._init_telegram_runtime(telegram_runtime)
        self._init_task_runtime(task_runtime)
        self._init_app_runtime(app_runtime)
        self._init_lease_runtime(lease_runtime)
        self._harden_sensitive_permissions()
        self._init_rewriter_runtime(rewriter_runtime)
        self._cleanup_activity_logs()
        self._rotate_activity_log_if_needed(force=False)

    def _cleanup_logs(self) -> None:
        retention_days = max(1, int(self.log_retention_days))
        cutoff = datetime.now().date() - timedelta(days=retention_days - 1)
        for path in self.logs_dir.glob("*.log"):
            m = re.search(r"(\\d{4}-\\d{2}-\\d{2})", path.stem)
            if not m:
                continue
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass

    def _cleanup_activity_logs(self) -> None:
        retention_days = max(1, int(self.activity_retention_days))
        cutoff = datetime.now().timestamp() - float(retention_days * 24 * 3600)
        activity_dir = self.activity_file.parent
        if not activity_dir.exists():
            return
        file_prefix = self.activity_file.name
        for path in activity_dir.glob(f"{file_prefix}*"):
            if path.name == file_prefix:
                pass
            elif not path.name.startswith(f"{file_prefix}."):
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def _rotate_activity_log_if_needed(self, *, force: bool = False) -> None:
        max_bytes = max(1, int(self.activity_max_bytes))
        backup_count = max(0, int(self.activity_backup_count))

        if not self.activity_file.exists():
            return
        if self.activity_file.stat().st_size <= max_bytes and not force:
            return

        if backup_count <= 0:
            try:
                self.activity_file.write_text("", encoding="utf-8")
            except Exception:
                try:
                    self.activity_file.unlink()
                except Exception:
                    pass
            return

        for idx in range(backup_count, 1, -1):
            src = Path(f"{self.activity_file}.{idx - 1}")
            dst = Path(f"{self.activity_file}.{idx}")
            if not src.exists():
                continue
            try:
                if dst.exists():
                    dst.unlink()
                src.replace(dst)
            except OSError:
                pass

        backup_1 = Path(f"{self.activity_file}.1")
        try:
            if backup_1.exists():
                backup_1.unlink()
            self.activity_file.replace(backup_1)
        except OSError:
            pass

    def _list_recent_tasks(
        self, chat_id: int, limit: int = 20, source_limit: int = 200
    ) -> list[dict[str, Any]]:
        return DaemonServiceTaskMixin._list_recent_tasks(
            self, chat_id=chat_id, limit=limit, source_limit=source_limit
        )
    def _daily_log_path(self) -> Path:
        return self.logs_dir / f"daemon-{datetime.now().strftime('%Y-%m-%d')}.log"

    def _recover_latest_thread_id_for_chat(self, chat_id: int) -> str:
        rows = self._list_recent_tasks(chat_id=chat_id, limit=20, source_limit=120)
        for row in rows:
            thread_id = _service_utils.compact_prompt_text(
                row.get("thread_id", ""), max_len=220
            )
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
        fence_match = re.search(
            r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.IGNORECASE | re.DOTALL
        )
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
            "[���� ê �ֱ� ��ȭ ���?(�ڵ�)]",
            f"- ����: �ֱ� {window_hours}�ð�",
            f"- ��ǥ �ټ�: �� {target}�� (�޽����� ������ �� ª�� �� ����)",
            "",
            "[��ȭ �帧]",
        ]

        try:
            payload = json.loads(self.store_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self.logger.warning(
                f"recent chat summary load failed chat_id={chat_id}: {exc}"
            )
            lines.append("- �޽��� ����Ҹ�? ���� ���� �����? �������� ���߽��ϴ�.")
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
            lines.append("- �ֱ� ��ȭ�� �����ϴ�.")
            return "\n".join(lines).strip()

        max_entries = max(target * 3, 90)
        omitted = 0
        if len(filtered) > max_entries:
            omitted = len(filtered) - max_entries
            filtered = filtered[-max_entries:]
        lines.insert(3, f"- ���� �޽���: {len(filtered)}��")
        if omitted > 0:
            lines.insert(4, f"- ������ �׸� ����: {omitted}��")

        for _, _, raw in filtered:
            msg_type = str(raw.get("type") or "").strip().lower() or "user"
            ts_text = (
                _service_utils.compact_prompt_text(raw.get("timestamp", ""), max_len=19)
                or "-"
            )
            text = _service_utils.compact_prompt_text(raw.get("text", ""), max_len=180)

            files = raw.get("files")
            file_count = len(files) if isinstance(files, list) else 0
            location = (
                raw.get("location") if isinstance(raw.get("location"), dict) else {}
            )
            suffix_parts: list[str] = []
            if file_count > 0:
                suffix_parts.append(f"÷�� {file_count}��")
            if location:
                lat = location.get("latitude")
                lon = location.get("longitude")
                if lat is not None and lon is not None:
                    suffix_parts.append(f"��ġ {lat},{lon}")
            suffix = f" [{' / '.join(suffix_parts)}]" if suffix_parts else ""

            if not text:
                text = "(�ؽ�Ʈ ����)"

            if msg_type == "bot":
                speaker = "BOT"
            else:
                name = _service_utils.compact_prompt_text(
                    raw.get("first_name", ""), max_len=20
                ) or _service_utils.compact_prompt_text(
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
            if self._handle_single_control_message(
                chat_id=chat_id, state=state, item=item
            ):
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
        if (
            text.startswith("__cb__:")
            and current_mode != UI_MODE_AWAITING_RESUME_CHOICE
        ):
            reply_text = (
                "���� ������ �����? ����Ǿ����. `TASK ���? ����(�ֱ�20)`�� �ٽ� ���� �ּ���."
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

        if text == BUTTON_TASK_LIST_RECENT20:
            self._clear_temp_task_seed(state)
            rows = self._list_recent_tasks(chat_id=chat_id, limit=20, source_limit=300)
            if not rows:
                self._clear_ui_mode(state)
                reply_text = "�ֱ� TASK 20���� �����帮�� ������, ��ȸ�� TASK�� �����ϴ�."
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
                candidate_ids, candidate_buttons, candidate_map = (
                    self._build_resume_choice_payload(rows=rows, max_count=20)
                )
                state["resume_choice_inline_only"] = True
                state["resume_candidates"] = candidate_ids
                state["resume_candidate_buttons"] = candidate_buttons
                state["resume_candidate_map"] = candidate_map
                self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
                header_text = self._render_task_list_text(rows=[], limit=20)
                footer_text = "�ֱټ����� ���ĵ˴ϴ�. Ư�� �۾�(TASK)�� �̾� �����Ͻ÷��� �ϴ��� ���� ��ư�� ���� �ּ���."
                reply_text = footer_text
                sent = self._send_task_cards_batch(
                    chat_id=chat_id,
                    rows=rows,
                    header_text=header_text,
                    footer_text=footer_text,
                    parse_mode="HTML",
                )
            self._finalize_control_message_if_sent(
                chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent
            )
            return True

        if text == BUTTON_TASK_GUIDE_VIEW:
            self._clear_temp_task_seed(state)
            guide_thread_id = self._resolve_task_agents_thread_id(state)
            if not guide_thread_id:
                self._clear_ui_mode(state)
                reply_text = (
                    "���� ���õ� TASK�� �����ϴ�.\n"
                    "���� `TASK ���? ����(�ֱ�20)` �Ǵ� `���� TASK �̾��ϱ�`�� TASK�� ������ �ּ���."
                )
                sent = self._send_control_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
                return True

            relative_path = self._task_agents_relative_path(
                chat_id=chat_id, thread_id=guide_thread_id
            )
            guide_text, exists = self._load_task_agents_text(
                chat_id=chat_id, thread_id=guide_thread_id
            )
            self._set_ui_mode(state, UI_MODE_AWAITING_TASK_GUIDE_EDIT)
            sent = False
            if exists and guide_text.strip():
                header_text = (
                    f"<b>TASK ��ħ ���� ����</b>\n"
                    f"- ����: <code>{self._escape_telegram_html(relative_path)}</code>\n"
                    "- �Ʒ� ���� Ȯ�� �� ���� ��û�� �ٷ� �����ּ���."
                )
                sent_header = self._telegram_send_text(
                    chat_id=chat_id,
                    text=header_text,
                    keyboard_rows=None,
                    request_max_attempts=1,
                    parse_mode="HTML",
                )
                sent = bool(sent or sent_header)
                chunks = _service_utils.split_text_chunks(
                    guide_text, max_chars=DEFAULT_TASK_GUIDE_TELEGRAM_CHUNK_CHARS
                )
                total_chunks = len(chunks)
                for idx, chunk in enumerate(chunks, start=1):
                    chunk_label = f"TASK ��ħ ���� ({idx}/{total_chunks})"
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
                    f"TASK ��ħ�� ������Ⱦ��. `{relative_path}` ���� ��û�� �����ֽø� "
                    "�ڵ����� �ش� ������ ���� �����մϴ�."
                )
            elif exists:
                reply_text = (
                    f"`{relative_path}` ������ ���������� ���� ������ ���? �ֽ��ϴ�.\n"
                    "���Ͻô� ��ħ ������ �����ֽø� �ڵ����� ������ ������ �ݿ��մϴ�."
                )
            else:
                reply_text = (
                    f"���� `{relative_path}` ������ �����ϴ�.\n"
                    "`TASK ��ħ �߰� ...` �Ǵ� `TASK ��ħ ���� ...`ó�� ��û���ֽø� "
                    "�ش� AGENTS.md�� ������ �� �ٷ� �ݿ��մϴ�."
                )
            sent_footer = self._telegram_send_text(
                chat_id=chat_id,
                text=reply_text,
                keyboard_rows=self._main_menu_keyboard_rows(),
                request_max_attempts=1,
            )
            sent = bool(sent or sent_footer)
            self._finalize_control_message_if_sent(
                chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent
            )
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
                reply_text = "���� ���� ȯ�濡���� �� �̸� ������ �������� �ʽ��ϴ�."
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
            shown_name = base_name if base_name else "(Ȯ�� ����)"
            reply_text = (
                "<b>�� �̸� ����</b>\n"
                f"���� �⺻ �̸�: <code>{self._escape_telegram_html(shown_name)}</code>\n"
                "���ϴ� ��Ī�� �Է��� �ּ���.\n"
                "���� ����: <code>�����̸�(��Ī)</code>"
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
        if (
            current_mode == UI_MODE_AWAITING_TEMP_TASK_DECISION
            and text not in temp_mode_passthrough_buttons
        ):
            if text == BUTTON_TASK_NEW:
                state["pending_new_task_summary"] = (
                    self._build_new_task_carryover_summary(chat_id=chat_id, state=state)
                )
                state["force_new_thread_once"] = True
                self._clear_selected_task_state(state)
                queued = list(state.get("queued_messages") or [])
                queued.extend(
                    self._build_temp_task_seed_batch(chat_id=chat_id, state=state)
                )
                state["queued_messages"] = self._dedupe_messages_by_message_id(
                    messages=queued
                )
                self._clear_temp_task_seed(state)
                self._clear_ui_mode(state)
                reply_text = (
                    "�� TASK�� �����ҰԿ�.\n" "���? ���� ������ ù ��û���� �̾ ó���մϴ�."
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
                    reply_text = "���Ͻô� TASK�� �˻��ϰڽ��ϴ�. �˻�� �Է����ּ���"
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
                        f"`{seed_query}`�� ������ TASK�� ã�� ���߽��ϴ�. "
                        "�ٸ� Ű���带 �Է��� �ּ���."
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

                candidate_ids, candidate_buttons, candidate_map = (
                    self._build_resume_choice_payload(
                        rows=candidates,
                        max_count=self.task_search_llm_limit,
                    )
                )
                state["resume_choice_inline_only"] = True
                state["resume_candidates"] = candidate_ids
                state["resume_candidate_buttons"] = candidate_buttons
                state["resume_candidate_map"] = candidate_map
                self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
                query_html = self._escape_telegram_html(seed_query)
                header_text = (
                    "<b>���� TASK �ĺ�</b>\n"
                    f"�˻���: <code>{query_html}</code>\n"
                    "<i>������ ���� ������ ���ĵ˴ϴ�. �׸��� ���� ��ư�� ���� �ּ���.</i>"
                )
                reply_text = header_text
                footer_text = "���Ͻô� TASK�� ���� ��ư�� ������ �ٷ� �̾ �����մϴ�."
                sent = self._send_task_cards_batch(
                    chat_id=chat_id,
                    rows=candidates,
                    header_text=header_text,
                    footer_text=footer_text,
                    parse_mode="HTML",
                )
                self._finalize_control_message_if_sent(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_text=reply_text,
                    sent=sent,
                )
                return True

            reply_text = "�� TASK�� ��������, ���� TASK�� �̾�� ��ư���� ������ �ּ���."
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
            reply_text = "���Ͻô� TASK�� �˻��ϰڽ��ϴ�. �˻�� �Է����ּ���"
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
            reply_text = "�� TASK�� ������ ���ø� �Է��� �ּ���."
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
            reply_text = "�޴��� ���ƿԾ��?."
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
                reply_text = (
                    f"`{text}`�� ������ TASK�� ã�� ���߽��ϴ�. �ٸ� Ű���带 �Է��� �ּ���."
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

            candidate_ids, candidate_buttons, candidate_map = (
                self._build_resume_choice_payload(
                    rows=candidates,
                    max_count=self.task_search_llm_limit,
                )
            )
            state["resume_choice_inline_only"] = True
            state["resume_candidates"] = candidate_ids
            state["resume_candidate_buttons"] = candidate_buttons
            state["resume_candidate_map"] = candidate_map
            self._set_ui_mode(state, UI_MODE_AWAITING_RESUME_CHOICE)
            query_html = self._escape_telegram_html(text)
            header_text = (
                "<b>���� TASK �ĺ�</b>\n"
                f"�˻���: <code>{query_html}</code>\n"
                "<i>������ ���� ������ ���ĵ˴ϴ�. �׸��� ���� ��ư�� ���� �ּ���.</i>"
            )
            reply_text = header_text
            footer_text = "���Ͻô� TASK�� ���� ��ư�� ������ �ٷ� �̾ �����մϴ�."
            sent = self._send_task_cards_batch(
                chat_id=chat_id,
                rows=candidates,
                header_text=header_text,
                footer_text=footer_text,
                parse_mode="HTML",
            )
            self._finalize_control_message_if_sent(
                chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent
            )
            return True

        if current_mode == UI_MODE_AWAITING_RESUME_CHOICE:
            candidate_ids = [
                _service_utils.normalize_task_id_token(v)
                for v in (state.get("resume_candidates") or [])
            ]
            candidate_ids = [v for v in candidate_ids if v]
            candidate_buttons = [
                _service_utils.normalize_ui_text(v)
                for v in (state.get("resume_candidate_buttons") or [])
                if _service_utils.normalize_ui_text(v)
            ]
            candidate_map_raw = (
                state.get("resume_candidate_map")
                if isinstance(state.get("resume_candidate_map"), dict)
                else {}
            )
            inline_only = bool(state.get("resume_choice_inline_only"))
            if callback_selected_task_id:
                selected_task_id = callback_selected_task_id
            else:
                selected_task_id = self._resolve_task_choice(
                    text=text, candidates=candidate_ids, candidate_map=candidate_map_raw
                )
            if (
                callback_selected_task_id
                and candidate_ids
                and selected_task_id not in candidate_ids
            ):
                reply_text = "���� ������ �����? ���ŵǾ����ϴ�. `TASK ���? ����(�ֱ�20)`�� �ٽ� ���� �ּ���."
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
                    reply_text = "���? �׸��� `����` ��ư�� �����ų�, ��ȣ(1,2,3...) �Ǵ� TASK ID�� �Է��� �ּ���."
                    keyboard_rows = None
                else:
                    reply_text = "�ĺ� ��ư�� �����ų�, ��ȣ(1,2,3...)�� �Է��� �ּ���."
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

            row = self._load_task_row(
                chat_id=chat_id, task_id=selected_task_id, include_instrunction=False
            )
            if not row:
                reply_text = f"{selected_task_id} TASK�� ã�� ���߽��ϴ�. �ٽ� ������ �ּ���."
                keyboard_rows = (
                    None
                    if inline_only
                    else (
                        _service_utils.build_candidate_keyboard_rows(
                            candidate_buttons,
                            main_menu_rows=self._main_menu_keyboard_rows(),
                        )
                        if candidate_buttons
                        else self._main_menu_keyboard_rows()
                    )
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
                f"{selected_task_id} TASK�� �̾ �����ҰԿ�.\n"
                "���� �̾ �� ������ �����ֽø� �ٷ� ó���մϴ�."
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
                self.logger.info(
                    f"task_select_delivery=send_first chat_id={chat_id} task_id={selected_task_id}"
                )
            elif callback_selected_task_id and callback_source_message_id > 0:
                self.logger.warning(
                    f"task_select_delivery send_first_failed "
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
                    self.logger.info(
                        f"task_select_delivery=fallback_edit chat_id={chat_id} task_id={selected_task_id} callback_message_id={callback_source_message_id}"
                    )
            if sent:
                self.logger.info(
                    f"task_select_focus_mode=no_post_edit chat_id={chat_id} task_id={selected_task_id}"
                )
            self._finalize_control_message_if_sent(
                chat_id=chat_id, message_id=message_id, reply_text=reply_text, sent=sent
            )
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
                reply_text = "��Ī�� ���? �ֽ��ϴ�. 1~32�� ��Ī�� �Է��� �ּ���."
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
            state["pending_new_task_summary"] = self._build_new_task_carryover_summary(
                chat_id=chat_id, state=state
            )
            state["force_new_thread_once"] = True
            self._clear_selected_task_state(state)
            self._clear_ui_mode(state)
            if str(state.get("active_turn_id") or "").strip():
                self._telegram_send_text(
                    chat_id=chat_id,
                    text="���� ���� ���� ������ ������ �� TASK�� �����մϴ�.",
                    keyboard_rows=self._main_menu_keyboard_rows(),
                    request_max_attempts=1,
                )
            # Do not consume this message: it must become the first instruction of the new task.
            return False

        if current_mode == UI_MODE_IDLE and not callback_selected_task_id:
            has_thread = bool(str(state.get("thread_id") or "").strip())
            has_active_turn = bool(str(state.get("active_turn_id") or "").strip())
            if (
                not has_thread
                and not has_active_turn
                and not bool(state.get("force_new_thread_once"))
            ):
                recovered_thread_id = self._recover_latest_thread_id_for_chat(
                    chat_id=chat_id
                )
                if recovered_thread_id:
                    state["thread_id"] = recovered_thread_id
                    state["app_generation"] = 0
                    self._clear_temp_task_seed(state)
                    self._save_app_server_state()
                    self._sync_app_server_session_meta(active_chat_id=chat_id)
                    self.logger.info(
                        f"cold_start_auto_resume_thread chat_id={chat_id} thread_id={recovered_thread_id} "
                        f"msg_id={msg_id}"
                    )
                    return False

                state["temp_task_first_text"] = text
                state["temp_task_first_message_id"] = msg_id
                state["temp_task_first_timestamp"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                self._set_ui_mode(state, UI_MODE_AWAITING_TEMP_TASK_DECISION)
                prompt_seed = self._escape_telegram_html(
                    _service_utils.compact_prompt_text(text, max_len=120)
                )
                reply_text = (
                    f"�����Ͻ� ����(<code>{prompt_seed}</code>)�� �������� �����ҰԿ�.\n"
                    "�� TASK�� ��������, ���� TASK�� �̾�� ������ �ּ���."
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
    def _dedupe_messages_by_message_id(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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
            pending = telegram.get_pending_messages(
                str(self.store_file), include_bot=False
            )
        except Exception as exc:
            self.logger.warning(f"pending snapshot failed: {exc}")
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
            location = (
                msg.get("location") if isinstance(msg.get("location"), dict) else None
            )
            messages.append(
                {
                    "message_id": msg_id,
                    "chat_id": chat_id,
                    "text": _service_utils.compact_prompt_text(
                        _service_utils.strip_new_command_prefix(
                            str(msg.get("text", ""))
                        ),
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
        return _service_utils.compact_prompt_text(
            mapping.get(normalized_task_id, ""), max_len=200
        )

    def _build_dynamic_request_line(
        self, pending_messages: list[dict[str, object]]
    ) -> str:
        if not pending_messages:
            rendered_refs = "����"
            rendered_requests = "���޽����� �����ϴ�."
        else:
            request_entries: list[str] = []
            ref_entries: list[str] = []
            for item in pending_messages:
                msg_id = int(item.get("message_id", 0))
                text = _service_utils.compact_prompt_text(
                    item.get("text", ""), max_len=320
                )
                if not text:
                    text = "(�ؽ�Ʈ ����, ÷��/��ġ ���� ����)"
                request_entries.append(f"[msg_{msg_id}] {text}")

                files_raw = item.get("files")
                file_types: list[str] = []
                if isinstance(files_raw, list):
                    for f in files_raw:
                        if isinstance(f, dict):
                            file_type = _service_utils.compact_prompt_text(
                                f.get("type", ""), max_len=30
                            )
                            if file_type:
                                file_types.append(file_type)
                file_types = sorted(set(file_types))
                file_info = (
                    f"{len(files_raw)}��[{','.join(file_types)}]"
                    if isinstance(files_raw, list) and files_raw
                    else "����"
                )

                location_info = "����"
                location_raw = item.get("location")
                if isinstance(location_raw, dict):
                    lat = location_raw.get("latitude")
                    lon = location_raw.get("longitude")
                    if lat is not None and lon is not None:
                        location_info = f"{lat},{lon}"

                if file_info != "����" or location_info != "����":
                    ref_entries.append(
                        f"msg_{msg_id}: files={file_info}, location={location_info}"
                    )

            rendered_refs = " | ".join(ref_entries) if ref_entries else "����"
            rendered_requests = " | ".join(request_entries)
        task_path_hint = self._task_path_hint_for_messages(pending_messages)

        return (
            f"��������: {rendered_refs}\n"
            "�۾� �޸𸮴� sonolbot-tasks ��ų ��Ģ�� ���� �� "
            f"({task_path_hint} ���б� �� ���� ���? ����ȭ).\n"
            "��û������ ó���� ��, ����ڿ���? ������ ���� �亯 ������ �ۼ��� �� "
            "(�������? ��ħ �ؼ�/��׶���? ���� ���? ���� ��û���׿� ���� �������� �亯�� ������ ��. "
            "ģ���ϰ� �����ϱ� ���� ���ϵ� �� �˾ƾ� �� ������ ���߸��� ����)\n"
            "���� �亯�� �ڷ��׷� HTML �Ľ� �������� �ۼ��� �� "
            "(�ʿ��? <b>, <code> �ּ� ���?, Markdown ������ �������? �� ��).\n"
            f"��û����: {rendered_requests}"
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
        if (
            runtime is None
            or telegram is None
            or not hasattr(telegram, "load_message_store")
        ):
            return ""
        try:
            store = telegram.load_message_store(str(self.store_file))
        except Exception:
            return ""
        messages = store.get("messages", [])
        if not isinstance(messages, list):
            return ""

        active_ids = {
            int(v) for v in (state.get("active_message_ids") or set()) if int(v) > 0
        }
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
            msg_text = _service_utils.compact_prompt_text(
                _service_utils.strip_new_command_prefix(str(raw.get("text", ""))),
                max_len=220,
            )
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
            self.logger.info(
                f"Stopping app-server (reason={reason}, pid={self.app_proc.pid})"
            )
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
        if (
            self.codex_run_meta
            and str(self.codex_run_meta.get("mode") or "").strip() == "app_server"
        ):
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
        if (
            now_epoch - self.app_last_restart_try_epoch
        ) < self.app_server_restart_backoff_sec:
            return False
        self.app_last_restart_try_epoch = now_epoch

        existing_pid = self._read_pid_file(self.codex_pid_file)
        if existing_pid > 0 and (
            self.app_proc is None or existing_pid != int(self.app_proc.pid)
        ):
            if _is_pid_alive(existing_pid):
                if self._is_codex_app_server_pid(existing_pid):
                    self.logger.info(
                        f"app_server_existing_pid_running pid={existing_pid}; skip duplicate start"
                    )
                    return False
                self.logger.warning(
                    f"stale codex pid file points to non app-server process pid={existing_pid}; clearing"
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
            self.logger.error(f"failed to start app-server: {exc}")
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
            {
                "clientInfo": {"name": "sonolbot-daemon", "version": "1.0"},
                "capabilities": {},
            },
            timeout_sec=20.0,
        )
        if init_result is None:
            self.logger.error(f"app-server initialize failed")
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
        self.logger.info(
            f"app-server started pid={self.app_proc.pid} listen={self.app_server_listen}"
        )
        return True

    def _group_pending_by_chat(
        self, messages: list[dict[str, Any]]
    ) -> dict[int, list[dict[str, Any]]]:
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
            parts.append("�߰� ���û���:")
        if carryover_summary:
            parts.append("���� ��ȭ �ٽ� ���?:\n" + carryover_summary)
        if selected_task_packet:
            parts.append(selected_task_packet)
        if resume_recent_chat_summary:
            parts.append("���� ê �ֱ� ��ȭ ���?:\n" + resume_recent_chat_summary)
        body = self._build_dynamic_request_line(messages)
        if task_packet:
            body = body + "\n\n�۾� �޸� ���?:\n" + task_packet
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
        queued_ids = {
            int(item.get("message_id"))
            for item in queued_messages
            if isinstance(item, dict)
        }
        failed_ids: set[int] = state.get("failed_reply_ids") or set()
        now_epoch = time.time()

        new_items: list[dict[str, Any]] = []
        for item in pending_chat_messages:
            msg_id = int(item.get("message_id", 0))
            if msg_id in active_ids or msg_id in queued_ids or msg_id in failed_ids:
                continue
            if self._is_message_recently_completed(msg_id, now_epoch=now_epoch):
                age_sec = self._recently_completed_message_age_sec(
                    msg_id, now_epoch=now_epoch
                )
                if age_sec >= 0.0:
                    self._log_recently_completed_drop(chat_id, msg_id, age_sec)
                continue
            new_items.append(item)
        return new_items

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self.logger.info(f"Signal received: {signum}")
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
                    if (
                        path.is_file()
                        and path.parent == self.logs_dir
                        and path.name.startswith("daemon-")
                    ):
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
        checker_path = (
            self.root / "src" / "sonolbot" / "tools" / "check_docs_alignment.py"
        )
        if not checker_path.exists():
            self.logger.warning(f"docs alignment checker missing: {checker_path}")
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
            self.logger.warning(f"docs alignment checker execution failed: {exc}")
            return
        if proc.returncode == 0:
            return
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if stdout:
            for line in stdout.splitlines():
                self.logger.info(f"[docs-check] {line}")
        if stderr:
            for line in stderr.splitlines():
                self.logger.info(f"[docs-check][stderr] {line}")

    def _run_main_cycle(self) -> int:
        self._cleanup_logs()
        self._cleanup_activity_logs()
        self._rotate_activity_log_if_needed(force=False)
        rc = self._run_quick_check()
        if rc not in (0, 1):
            self.logger.info(f"quick_check failed rc={rc}")
            return rc

        self._app_process_cycle()
        return rc

    def drain_pending_once(
        self, max_cycles: int = 120, sleep_sec: float = 1.0, use_lock: bool = True
    ) -> int:
        if not shutil.which("codex"):
            self.logger.error("codex CLI not found in PATH")
            return 1

        locked = False
        if use_lock:
            try:
                self._acquire_lock()
                locked = True
            except Exception as exc:
                self.logger.error(f"cannot acquire daemon lock for drain mode: {exc}")
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

            self.logger.warning(f"drain mode reached max_cycles={cycles} before idle")
            return 1
        finally:
            self._stop_app_server("drain_mode_done")
            if locked:
                self._release_lock()

    def run(self) -> int:
        if not shutil.which("codex"):
            self.logger.error("codex CLI not found in PATH")
            return 1

        signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._handle_signal)

        try:
            self._acquire_lock()
        except Exception as exc:
            self.logger.error(f"{exc}")
            return 1
        self.logger.info(
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
            self.logger.info("Daemon stopped")
        return 0


