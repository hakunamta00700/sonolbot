from __future__ import annotations

from sonolbot.core.daemon import service_utils as _service_utils
from sonolbot.core.daemon.runtime_shared import *


class DaemonServiceTelegramRuntime:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.telegram_runtime: dict[str, object] | None = None
        self.telegram_skill: object | None = None


class DaemonServiceTelegramMixin:
    def _init_telegram_runtime(self, telegram_runtime: DaemonServiceTelegramRuntime | None = None) -> None:
        if telegram_runtime is not None and not isinstance(telegram_runtime, DaemonServiceTelegramRuntime):
            raise TypeError("telegram_runtime must be DaemonServiceTelegramRuntime")
        if telegram_runtime is None:
            telegram_runtime = DaemonServiceTelegramRuntime(self)
        self._telegram_runtime_component = telegram_runtime

    def _get_telegram_runtime(self) -> DaemonServiceTelegramRuntime | None:
        runtime = getattr(self, "_telegram_runtime_component", None)
        if isinstance(runtime, DaemonServiceTelegramRuntime):
            return runtime
        return None

    @staticmethod
    def _normalize_telegram_parse_mode(parse_mode: object) -> str:
        return _service_utils.normalize_telegram_parse_mode(parse_mode)

    def _resolve_telegram_parse_mode(self, parse_mode: str | None) -> str | None:
        requested = self._normalize_telegram_parse_mode(parse_mode)
        if requested:
            return requested
        if not self.telegram_force_parse_mode:
            return None
        fallback_mode = self._normalize_telegram_parse_mode(self.telegram_default_parse_mode)
        if fallback_mode:
            return fallback_mode
        return None

    @staticmethod
    def _sanitize_telegram_text_for_parse_mode(text: object, parse_mode: str | None) -> str:
        rendered = str(text or "")
        normalized_mode = DaemonServiceTelegramMixin._normalize_telegram_parse_mode(parse_mode)
        if normalized_mode != "HTML":
            return rendered
        rendered = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", rendered)
        return rendered

    def _get_telegram_runtime_skill(self) -> tuple[dict[str, object] | None, object | None]:
        runtime = self._get_telegram_runtime()
        if runtime is None:
            return None, None
        if runtime.telegram_runtime is not None and runtime.telegram_skill is not None:
            return runtime.telegram_runtime, runtime.telegram_skill
        try:
            runtime_data = build_telegram_runtime()
            skill = get_telegram_skill()
        except Exception as exc:
            self.logger.warning(f"telegram runtime init failed: {exc}")
            return None, None
        runtime.telegram_runtime = runtime_data
        runtime.telegram_skill = skill
        return runtime_data, skill

    @staticmethod
    def _escape_telegram_html(value: object) -> str:
        return html.escape(str(value or "").strip(), quote=True)

    def _telegram_get_me_name(self, request_max_attempts: int = 1) -> str:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None or not hasattr(telegram, "get_me"):
            return ""
        try:
            try:
                profile = telegram.get_me(
                    runtime,
                    request_max_attempts=request_max_attempts,
                )
            except TypeError:
                profile = telegram.get_me(runtime)
        except Exception as exc:
            self.logger.warning(f"get_me failed: {exc}")
            return ""
        if not isinstance(profile, dict):
            return ""
        return _service_utils.compact_prompt_text(profile.get("first_name", ""), max_len=80)

    def _telegram_get_my_name(self, request_max_attempts: int = 1) -> str:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None or not hasattr(telegram, "get_my_name"):
            return ""
        try:
            try:
                value = telegram.get_my_name(
                    runtime,
                    language_code="",
                    request_max_attempts=request_max_attempts,
                )
            except TypeError:
                value = telegram.get_my_name(runtime, language_code="")
        except Exception as exc:
            self.logger.warning(f"get_my_name failed: {exc}")
            return ""
        return _service_utils.compact_prompt_text(value, max_len=80)

    def _telegram_set_my_name(self, target_name: str, request_max_attempts: int = 1) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None or not hasattr(telegram, "set_my_name"):
            return False
        try:
            try:
                return bool(
                    telegram.set_my_name(
                        runtime,
                        name=str(target_name or ""),
                        language_code="",
                        request_max_attempts=request_max_attempts,
                    )
                )
            except TypeError:
                return bool(
                    telegram.set_my_name(
                        runtime,
                        name=str(target_name or ""),
                        language_code="",
                    )
                )
        except Exception as exc:
            self.logger.warning(f"set_my_name failed: {exc}")
            return False

    def _telegram_send_text_once(
        self,
        runtime: dict[str, Any],
        telegram: Any,
        chat_id: int,
        text: str,
        request_max_attempts: int = 1,
        keyboard_rows: list[list[str]] | None = None,
        inline_keyboard_rows: list[list[dict[str, str]]] | None = None,
        message_id: int | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        payload_text = self._sanitize_telegram_text_for_parse_mode(text, parse_mode)
        action = "edit" if message_id else "send"
        target = f" message_id={message_id}" if message_id else ""
        try:
            if message_id is not None:
                try:
                    return bool(
                        telegram.edit_message_text(
                            runtime,
                            chat_id=int(chat_id),
                            message_id=int(message_id),
                            text=payload_text,
                            inline_keyboard_rows=inline_keyboard_rows,
                            request_max_attempts=request_max_attempts,
                            parse_mode=parse_mode,
                        )
                    )
                except TypeError:
                    return bool(
                        telegram.edit_message_text(
                            runtime,
                            chat_id=int(chat_id),
                            message_id=int(message_id),
                            text=payload_text,
                            inline_keyboard_rows=inline_keyboard_rows,
                            request_max_attempts=request_max_attempts,
                        )
                    )
            if inline_keyboard_rows and hasattr(telegram, "send_text_with_inline_keyboard"):
                try:
                    return bool(
                        telegram.send_text_with_inline_keyboard(
                            runtime,
                            chat_id=int(chat_id),
                            text=payload_text,
                            inline_keyboard_rows=inline_keyboard_rows,
                            request_max_attempts=request_max_attempts,
                            parse_mode=parse_mode,
                        )
                    )
                except TypeError:
                    return bool(
                        telegram.send_text_with_inline_keyboard(
                            runtime,
                            chat_id=int(chat_id),
                            text=payload_text,
                            inline_keyboard_rows=inline_keyboard_rows,
                            request_max_attempts=request_max_attempts,
                        )
                    )
            if keyboard_rows and hasattr(telegram, "send_text_with_keyboard"):
                try:
                    return bool(
                        telegram.send_text_with_keyboard(
                            runtime,
                            chat_id=int(chat_id),
                            text=payload_text,
                            keyboard_rows=keyboard_rows,
                            resize_keyboard=True,
                            one_time_keyboard=False,
                            request_max_attempts=request_max_attempts,
                            parse_mode=parse_mode,
                        )
                    )
                except TypeError:
                    return bool(
                        telegram.send_text_with_keyboard(
                            runtime,
                            chat_id=int(chat_id),
                            text=payload_text,
                            keyboard_rows=keyboard_rows,
                            resize_keyboard=True,
                            one_time_keyboard=False,
                            request_max_attempts=request_max_attempts,
                        )
                    )
            try:
                return bool(
                    telegram.send_text_raw(
                        runtime,
                        chat_id=int(chat_id),
                        text=payload_text,
                        request_max_attempts=request_max_attempts,
                        parse_mode=parse_mode,
                    )
                )
            except TypeError:
                return bool(
                    telegram.send_text_raw(
                        runtime,
                        chat_id=int(chat_id),
                        text=payload_text,
                        request_max_attempts=request_max_attempts,
                    )
                )
        except Exception as exc:
            self.logger.warning(f"telegram {action} failed chat_id={chat_id}{target}: {exc}")
            return False

    def _telegram_send_text(
        self,
        chat_id: int,
        text: str,
        request_max_attempts: int = 1,
        keyboard_rows: list[list[str]] | None = None,
        inline_keyboard_rows: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return False
        effective_parse_mode = self._resolve_telegram_parse_mode(parse_mode)
        normalized_text = self._sanitize_telegram_text_for_parse_mode(text, effective_parse_mode)
        sent = self._telegram_send_text_once(
            runtime=runtime,
            telegram=telegram,
            chat_id=chat_id,
            text=normalized_text,
            request_max_attempts=request_max_attempts,
            keyboard_rows=keyboard_rows,
            inline_keyboard_rows=inline_keyboard_rows,
            parse_mode=effective_parse_mode,
        )
        if sent:
            return True
        if effective_parse_mode and self.telegram_parse_fallback_raw_on_fail:
            last_err = None
            try:
                last_err = runtime.get("_telegram_last_error")  # type: ignore[attr-defined]
            except Exception:
                last_err = None
            kind = str(last_err.get("kind") if isinstance(last_err, dict) else "").strip().lower()
            is_network = kind == "network"
            is_parse = False
            if isinstance(last_err, dict) and kind == "http":
                try:
                    status_code = int(last_err.get("status_code") or 0)
                except Exception:
                    status_code = 0
                body = str(last_err.get("body") or "")
                if status_code == 400 and ("can't parse entities" in body or "Unsupported start tag" in body):
                    is_parse = True

            if is_network:
                self.logger.warning(
                    f"telegram send retry with same parse_mode due to network error "
                    f"chat_id={chat_id} parse_mode={effective_parse_mode}"
                )
                return self._telegram_send_text_once(
                    runtime=runtime,
                    telegram=telegram,
                    chat_id=chat_id,
                    text=normalized_text,
                    request_max_attempts=request_max_attempts,
                    keyboard_rows=keyboard_rows,
                    inline_keyboard_rows=inline_keyboard_rows,
                    parse_mode=effective_parse_mode,
                )

            if is_parse:
                self.logger.warning(
                    f"telegram send retry without parse_mode due to parse error "
                    f"chat_id={chat_id} parse_mode={effective_parse_mode}"
                )
                return self._telegram_send_text_once(
                    runtime=runtime,
                    telegram=telegram,
                    chat_id=chat_id,
                    text=normalized_text,
                    request_max_attempts=request_max_attempts,
                    keyboard_rows=keyboard_rows,
                    inline_keyboard_rows=inline_keyboard_rows,
                    parse_mode=None,
                )
        return False

    def _telegram_edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        inline_keyboard_rows: list[list[dict[str, str]]] | None = None,
        request_max_attempts: int = 1,
        parse_mode: str | None = None,
    ) -> bool:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return False
        if not hasattr(telegram, "edit_message_text"):
            return False
        effective_parse_mode = self._resolve_telegram_parse_mode(parse_mode)
        normalized_text = self._sanitize_telegram_text_for_parse_mode(text, effective_parse_mode)
        edited = self._telegram_send_text_once(
            runtime=runtime,
            telegram=telegram,
            chat_id=chat_id,
            message_id=message_id,
            text=normalized_text,
            request_max_attempts=request_max_attempts,
            inline_keyboard_rows=inline_keyboard_rows,
            parse_mode=effective_parse_mode,
        )
        if edited:
            return True
        if effective_parse_mode and self.telegram_parse_fallback_raw_on_fail:
            last_err = None
            try:
                last_err = runtime.get("_telegram_last_error")  # type: ignore[attr-defined]
            except Exception:
                last_err = None
            kind = str(last_err.get("kind") if isinstance(last_err, dict) else "").strip().lower()
            is_network = kind == "network"
            is_parse = False
            if isinstance(last_err, dict) and kind == "http":
                try:
                    status_code = int(last_err.get("status_code") or 0)
                except Exception:
                    status_code = 0
                body = str(last_err.get("body") or "")
                if status_code == 400 and ("can't parse entities" in body or "Unsupported start tag" in body):
                    is_parse = True

            if is_network:
                self.logger.warning(
                    f"telegram edit retry with same parse_mode due to network error "
                    f"chat_id={chat_id} message_id={message_id} parse_mode={effective_parse_mode}"
                )
                return self._telegram_send_text_once(
                    runtime=runtime,
                    telegram=telegram,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=normalized_text,
                    request_max_attempts=request_max_attempts,
                    inline_keyboard_rows=inline_keyboard_rows,
                    parse_mode=effective_parse_mode,
                )

            if is_parse:
                self.logger.warning(
                    f"telegram edit retry without parse_mode due to parse error "
                    f"chat_id={chat_id} message_id={message_id} parse_mode={effective_parse_mode}"
                )
                return self._telegram_send_text_once(
                    runtime=runtime,
                    telegram=telegram,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=normalized_text,
                    request_max_attempts=request_max_attempts,
                    inline_keyboard_rows=inline_keyboard_rows,
                    parse_mode=None,
                )
        return False

    def _finalize_control_message(self, chat_id: int, message_id: int, reply_text: str) -> None:
        runtime, telegram = self._get_telegram_runtime_skill()
        if runtime is None or telegram is None:
            return
        try:
            telegram.save_bot_response(
                store_path=str(self.store_file),
                chat_id=int(chat_id),
                text=str(reply_text or ""),
                reply_to_message_ids=[int(message_id)],
            )
        except Exception as exc:
            self.logger.warning(f"control response save failed chat_id={chat_id} msg_id={message_id}: {exc}")

        try:
            changed = int(telegram.mark_messages_processed(str(self.store_file), [int(message_id)]))
        except Exception as exc:
            self.logger.warning(f"control mark processed failed chat_id={chat_id} msg_id={message_id}: {exc}")
            changed = 0
        if changed > 0:
            self._remember_completed_message_ids({int(message_id)})

    def _finalize_control_message_if_sent(
        self,
        chat_id: int,
        message_id: int,
        reply_text: str,
        sent: bool,
    ) -> None:
        if sent:
            self._finalize_control_message(chat_id=chat_id, message_id=message_id, reply_text=reply_text)

    def _send_control_reply(
        self,
        chat_id: int,
        message_id: int,
        reply_text: str,
        *,
        keyboard_rows: list[list[str]] | None = None,
        inline_keyboard_rows: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
        request_max_attempts: int = 1,
    ) -> bool:
        sent = self._telegram_send_text(
            chat_id=chat_id,
            text=reply_text,
            keyboard_rows=keyboard_rows,
            inline_keyboard_rows=inline_keyboard_rows,
            request_max_attempts=request_max_attempts,
            parse_mode=parse_mode,
        )
        self._finalize_control_message_if_sent(
            chat_id=chat_id,
            message_id=message_id,
            reply_text=reply_text,
            sent=sent,
        )
        return sent



