from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import service_utils as _service_utils


class DaemonServiceRewriterRuntime:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.rewriter_proc: subprocess.Popen[str] | None = None
        self.rewriter_json_send_lock = threading.Lock()
        self.rewriter_req_lock = threading.Lock()
        self.rewriter_pending_responses: dict[int, queue.Queue[dict[str, Any]] ] = {}
        self.rewriter_event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.rewriter_next_request_id = 1
        self.rewriter_turn_results: dict[str, dict[str, Any]] = {}
        self.rewriter_chat_threads: dict[int, str] = {}
        self.rewriter_last_restart_try_epoch = 0.0
        self._lock: _ProcessFileLock | None = None
        self._lock_busy_logged_at = 0.0

    @property
    def _owner(self) -> Any:
        return self.service

    def load_state(self) -> None:
        payload = _service_utils.read_json_dict(self._owner.agent_rewriter_state_file)
        if not isinstance(payload, dict):
            return

        raw_threads = payload.get("chat_threads")
        if isinstance(raw_threads, dict):
            threads: dict[int, str] = {}
            for raw_chat_id, raw_thread in raw_threads.items():
                try:
                    chat_id = int(raw_chat_id)
                except Exception:
                    continue
                thread_id = str(raw_thread or "").strip()
                if thread_id:
                    threads[chat_id] = thread_id
            self.rewriter_chat_threads = threads

        next_request_id = payload.get("next_request_id")
        if isinstance(next_request_id, int):
            self.rewriter_next_request_id = max(1, next_request_id)

    def save_state(self) -> None:
        payload: dict[str, Any] = {
            "version": 1,
            "saved_at": time.time(),
            "next_request_id": self.rewriter_next_request_id,
            "chat_threads": {
                str(chat_id): thread_id for chat_id, thread_id in self.rewriter_chat_threads.items()
            },
        }
        _service_utils.write_json_dict_atomic(self._owner.agent_rewriter_state_file, payload)

    def read_pid_file(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:
            return 0

    def is_codex_app_server_pid(self, pid: int) -> bool:
        try:
            pid_value = int(pid)
        except Exception:
            return False
        if not _is_pid_alive(pid_value):
            return False
        if os.name == "nt":
            return True
        try:
            cmdline = Path(f"/proc/{pid_value}/cmdline").read_text(errors="ignore")
            return ("codex" in cmdline.lower()) and ("app-server" in cmdline.lower())
        except Exception:
            return True

    def acquire_lock(self) -> bool:
        timeout_sec = max(0.0, float(getattr(self._owner, "file_lock_wait_timeout_sec", 0.0)))
        deadline = time.time() + timeout_sec
        last_warned = 0.0
        while True:
            try:
                if self._lock is None:
                    self._lock = _ProcessFileLock(
                        self._owner.agent_rewriter_lock_file,
                        self._owner.agent_rewriter_pid_file,
                        "agent-rewriter",
                    )
                self._lock.acquire()
                self._lock_busy_logged_at = 0.0
                return True
            except Exception as exc:
                self._lock = None
                if time.time() >= deadline:
                    if time.time() - self._lock_busy_logged_at >= 1.0:
                        try:
                            self._owner._log(f"WARN: failed to acquire agent-rewriter lock: {exc}")
                        except Exception:
                            pass
                        self._lock_busy_logged_at = time.time()
                    return False
                if time.time() - last_warned >= 1.0:
                    try:
                        self._owner._log(f"WARN: waiting for agent-rewriter lock: {exc}")
                    except Exception:
                        pass
                    last_warned = time.time()
                time.sleep(min(0.2, max(0.05, timeout_sec / 8.0)))

    def release_lock(self) -> None:
        if self._lock is None:
            return
        try:
            self._lock.release()
        finally:
            self._lock = None

    def write_log(self, prefix: str, line: str) -> None:
        append_timestamped_log_line(self._owner.agent_rewriter_log_file, prefix, line)

    def build_codex_app_server_cmd(self, role: str = "app-server") -> list[str]:
        listen = str(getattr(self._owner, "app_server_listen", "stdio://")).strip()
        if not listen:
            listen = "stdio://"
        return ["codex", "app-server", "--listen", listen]


class DaemonServiceRewriterMixin:

    def _get_rewriter_runtime(self) -> DaemonServiceRewriterRuntime | None:
        runtime = getattr(self, "_rewriter_runtime_component", None)
        if isinstance(runtime, DaemonServiceRewriterRuntime):
            return runtime
        return None

    def _init_rewriter_runtime(self, runtime: DaemonServiceRewriterRuntime | None = None) -> None:
        if runtime is not None and not isinstance(runtime, DaemonServiceRewriterRuntime):
            raise TypeError("rewriter_runtime must be DaemonServiceRewriterRuntime")
        if runtime is None:
            runtime = DaemonServiceRewriterRuntime(self)
        self._rewriter_runtime_component = runtime
        runtime.load_state()

    @property
    def rewriter_proc(self) -> subprocess.Popen[str] | None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return None
        return runtime.rewriter_proc

    @rewriter_proc.setter
    def rewriter_proc(self, value: subprocess.Popen[str] | None) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_proc = value

    @property
    def rewriter_json_send_lock(self) -> threading.Lock:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return threading.Lock()
        return runtime.rewriter_json_send_lock

    @rewriter_json_send_lock.setter
    def rewriter_json_send_lock(self, value: threading.Lock) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_json_send_lock = value

    @property
    def rewriter_req_lock(self) -> threading.Lock:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return threading.Lock()
        return runtime.rewriter_req_lock

    @rewriter_req_lock.setter
    def rewriter_req_lock(self, value: threading.Lock) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_req_lock = value

    @property
    def rewriter_pending_responses(self) -> dict[int, queue.Queue[dict[str, Any]]]:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return {}
        return runtime.rewriter_pending_responses

    @rewriter_pending_responses.setter
    def rewriter_pending_responses(self, value: dict[int, queue.Queue[dict[str, Any]]]) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_pending_responses = value

    @property
    def rewriter_event_queue(self) -> queue.Queue[dict[str, Any]]:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return queue.Queue()
        return runtime.rewriter_event_queue

    @rewriter_event_queue.setter
    def rewriter_event_queue(self, value: queue.Queue[dict[str, Any]]) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_event_queue = value

    @property
    def rewriter_next_request_id(self) -> int:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return 1
        return runtime.rewriter_next_request_id

    @rewriter_next_request_id.setter
    def rewriter_next_request_id(self, value: int) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_next_request_id = value

    @property
    def rewriter_turn_results(self) -> dict[str, dict[str, Any]]:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return {}
        return runtime.rewriter_turn_results

    @rewriter_turn_results.setter
    def rewriter_turn_results(self, value: dict[str, dict[str, Any]]) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_turn_results = value

    @property
    def rewriter_chat_threads(self) -> dict[int, str]:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return {}
        return runtime.rewriter_chat_threads

    @rewriter_chat_threads.setter
    def rewriter_chat_threads(self, value: dict[int, str]) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_chat_threads = value

    @property
    def rewriter_last_restart_try_epoch(self) -> float:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return 0.0
        return runtime.rewriter_last_restart_try_epoch

    @rewriter_last_restart_try_epoch.setter
    def rewriter_last_restart_try_epoch(self, value: float) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.rewriter_last_restart_try_epoch = value

    def _load_agent_rewriter_state(self) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.load_state()

    def _save_agent_rewriter_state(self) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.save_state()

    def _read_pid_file(self, path: Path) -> int:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return 0
        return runtime.read_pid_file(path)

    def _is_codex_app_server_pid(self, pid: int) -> bool:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return _is_pid_alive(int(pid))
        return runtime.is_codex_app_server_pid(pid)

    def _acquire_agent_rewriter_lock(self) -> bool:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return False
        return runtime.acquire_lock()

    def _release_agent_rewriter_lock(self) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.release_lock()

    def _build_codex_app_server_cmd(self, role: str = "app-server") -> list[str]:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            listen = str(getattr(self, "app_server_listen", "stdio://")).strip() or "stdio://"
            return ["codex", "app-server", "--listen", listen]
        return runtime.build_codex_app_server_cmd(role=role)

    def _write_agent_rewriter_log(self, prefix: str, line: str) -> None:
        runtime = self._get_rewriter_runtime()
        if runtime is None:
            return
        runtime.write_log(prefix, line)

    def _write_app_server_log(self, prefix: str, line: str) -> None:
        try:
            append_timestamped_log_line(self.app_server_log_file, prefix, line)
        except Exception:
            pass

    def _secure_file(self, path: Path) -> None:
        try:
            path.chmod(SECURE_FILE_MODE)
        except Exception:
            pass

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
