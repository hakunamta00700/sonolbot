from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import service_utils as _service_utils

class DaemonServiceAppMixin:

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

