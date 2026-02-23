from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import service_utils as _service_utils

try:
    import errno
except Exception:  # pragma: no cover
    errno = None

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except Exception:  # pragma: no cover
    msvcrt = None


class DaemonServiceAppRuntime:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.app_proc: subprocess.Popen[str] | None = None
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
        self._app_server_lock_fd: int | None = None
        self._app_server_lock_busy_logged_at = 0.0

    @property
    def _owner(self) -> Any:
        return self.service

    def load_state(self) -> None:
        self.app_chat_states = {}
        self.app_thread_to_chat = {}
        for chat_id, thread_id in _service_utils.load_thread_state_map(self._owner.app_server_state_file).items():
            state = self._owner._new_chat_state()
            if thread_id:
                state["thread_id"] = thread_id
                self.app_thread_to_chat[thread_id] = chat_id
            self.app_chat_states[chat_id] = state

    def save_state(self) -> None:
        data_map: dict[int, str] = {}
        for chat_id, state in self.app_chat_states.items():
            thread_id = str(state.get("thread_id") or "").strip()
            if not thread_id:
                continue
            data_map[chat_id] = thread_id
        if not _service_utils.write_json_dict(
            self._owner.app_server_state_file, _service_utils.build_session_thread_payload(data_map)
        ):
            self._owner._log(f"WARN: failed to save app-server state: write failed")
            return
        try:
            self.secure_file(self._owner.app_server_state_file)
        except OSError as exc:
            self._owner._log(f"WARN: failed to secure app-server state: {exc}")

    def write_log(self, prefix: str, line: str) -> None:
        if not _service_utils.append_timestamped_log_line(self._owner.app_server_log_file, prefix, line):
            return
        try:
            self.secure_file(self._owner.app_server_log_file)
        except OSError:
            pass

    def get_chat_state(self, chat_id: int) -> dict[str, Any]:
        state = self.app_chat_states.get(chat_id)
        if state is None:
            state = self._owner._new_chat_state()
            self.app_chat_states[chat_id] = state
        return state

    def write_codex_session_meta(self) -> None:
        if not self._owner.codex_run_meta:
            return
        payload = dict(self._owner.codex_run_meta)
        payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._owner.codex_session_meta_file.parent.mkdir(parents=True, exist_ok=True)
            self._owner.codex_session_meta_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.secure_file(self._owner.codex_session_meta_file)
        except OSError as exc:
            self._owner._log(f"WARN: failed to write codex session meta: {exc}")

    def set_runtime_env(self, key: str, value: str) -> None:
        self._owner.env[key] = value
        os.environ[key] = value

    def sync_codex_runtime_env(
        self,
        *,
        run_id: str,
        mode: str,
        started_at: str,
        resume_target: str,
        session_id: str,
        thread_id: str = "",
    ) -> None:
        self.set_runtime_env("SONOLBOT_CODEX_RUN_ID", run_id)
        self.set_runtime_env("SONOLBOT_CODEX_MODE", mode)
        self.set_runtime_env("SONOLBOT_CODEX_STARTED_AT", started_at)
        self.set_runtime_env("SONOLBOT_CODEX_RESUME_TARGET", resume_target)
        self.set_runtime_env("SONOLBOT_CODEX_SESSION_ID", session_id)
        self.set_runtime_env("SONOLBOT_CODEX_THREAD_ID", thread_id)
        self.set_runtime_env("SONOLBOT_CODEX_CLI_VERSION", self._owner.codex_cli_version)
        self.set_runtime_env("SONOLBOT_CODEX_MODEL", self._owner.codex_model)
        self.set_runtime_env("SONOLBOT_CODEX_REASONING_EFFORT", self._owner.codex_reasoning_effort)
        self.set_runtime_env("SONOLBOT_CODEX_SESSION_META_FILE", str(self._owner.codex_session_meta_file))
        self._owner.env.setdefault("SONOLBOT_STORE_CODEX_SESSION", "1")
        os.environ.setdefault("SONOLBOT_STORE_CODEX_SESSION", "1")

    def sync_app_server_session_meta(self, active_chat_id: int | None = None) -> None:
        if not self._owner.codex_run_meta:
            return
        if str(self._owner.codex_run_meta.get("mode") or "").strip() != "app_server":
            return

        sessions: dict[str, dict[str, object]] = {}
        thread_ids_by_chat: dict[str, str] = {}
        first_thread = ""
        active_thread = ""
        for chat_id in sorted(self.app_chat_states.keys()):
            state = self.get_chat_state(chat_id)
            thread_id = str(state.get("thread_id") or "").strip()
            if not thread_id:
                continue
            active_turn_id = str(state.get("active_turn_id") or "").strip()
            payload: dict[str, object] = {"thread_id": thread_id}
            if active_turn_id:
                payload["active_turn_id"] = active_turn_id
            queued_messages = state.get("queued_messages") or []
            if isinstance(queued_messages, list) and queued_messages:
                payload["queued_count"] = len(queued_messages)
            sessions[str(chat_id)] = payload
            thread_ids_by_chat[str(chat_id)] = thread_id
            if not first_thread:
                first_thread = thread_id
            if active_chat_id is not None and chat_id == active_chat_id:
                active_thread = thread_id

        if active_chat_id is None:
            current_thread_id = str(self._owner.codex_run_meta.get("current_thread_id") or "").strip()
        else:
            current_thread_id = active_thread

        self._owner.codex_run_meta["transport"] = "app_server"
        self._owner.codex_run_meta["listen"] = self._owner.app_server_listen
        self._owner.codex_run_meta["app_server_generation"] = self.app_proc_generation
        self._owner.codex_run_meta["app_server_pid"] = self.app_proc.pid if self._owner._app_is_running() and self.app_proc else 0
        self._owner.codex_run_meta["thread_ids_by_chat"] = thread_ids_by_chat
        self._owner.codex_run_meta["sessions"] = sessions
        if active_chat_id is not None:
            self._owner.codex_run_meta["last_active_chat_id"] = active_chat_id
        if current_thread_id:
            self._owner.codex_run_meta["current_thread_id"] = current_thread_id
            self._owner.codex_run_meta["thread_id"] = current_thread_id
        elif self._owner.codex_run_meta.get("current_thread_id"):
            self._owner.codex_run_meta["current_thread_id"] = ""
            self._owner.codex_run_meta["thread_id"] = ""

        fallback_session_id = current_thread_id or first_thread
        if fallback_session_id:
            self._owner.codex_run_meta["session_id"] = fallback_session_id
            self._owner.codex_run_meta["session_id_kind"] = "thread_id_alias"

        self.sync_codex_runtime_env(
            run_id=str(self._owner.codex_run_meta.get("run_id") or ""),
            mode="app_server",
            started_at=str(self._owner.codex_run_meta.get("started_at") or ""),
            resume_target="",
            session_id=str(self._owner.codex_run_meta.get("session_id") or ""),
            thread_id=(current_thread_id or fallback_session_id),
        )
        self.write_codex_session_meta()

    def read_pid_file(self, path: Path) -> int:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:
            return 0

    def pid_cmdline(self, pid: int) -> str:
        if pid <= 0:
            return ""
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists():
            try:
                raw = proc_cmdline.read_bytes()
                if raw:
                    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            except Exception:
                pass
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            )
            if proc.returncode == 0:
                return str(proc.stdout or "").strip()
        except Exception:
            pass
        return ""

    def is_codex_app_server_pid(self, pid: int) -> bool:
        if pid <= 0 or not _is_pid_alive(pid):
            return False
        cmdline = self.pid_cmdline(pid).lower()
        if not cmdline:
            return True
        return ("codex" in cmdline) and ("app-server" in cmdline)

    @staticmethod
    def try_lock_fd_nonblocking(fd: int) -> bool:
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError as exc:
                if errno is not None and exc.errno in (errno.EACCES, errno.EAGAIN):
                    return False
                raise
        if msvcrt is not None:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        return True

    @staticmethod
    def unlock_fd(fd: int) -> None:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

    @contextmanager
    def exclusive_file_lock(self, lock_path: Path, wait_timeout_sec: float | None = None):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.secure_dir(lock_path.parent)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, SECURE_FILE_MODE)
        self.secure_file(lock_path)
        acquired = False
        timeout_sec = max(0.05, float(wait_timeout_sec or self._owner.file_lock_wait_timeout_sec))
        deadline = time.time() + timeout_sec
        try:
            while True:
                if self.try_lock_fd_nonblocking(fd):
                    acquired = True
                    break
                if time.time() >= deadline:
                    raise TimeoutError(f"lock timeout: {lock_path}")
                time.sleep(0.05)
            yield
        finally:
            if acquired:
                self.unlock_fd(fd)
            try:
                os.close(fd)
            except OSError:
                pass

    def log_app_server_lock_busy(self) -> None:
        now_epoch = time.time()
        if (now_epoch - self._app_server_lock_busy_logged_at) < max(5.0, float(self._owner.poll_interval_sec)):
            return
        self._app_server_lock_busy_logged_at = now_epoch
        pid_hint = self.read_pid_file(self._owner.codex_pid_file)
        self._owner._log(
            f"app_server_lock_busy path={self._owner.app_server_lock_file} pid_hint={pid_hint or '-'}"
        )

    def acquire_lock(self) -> bool:
        if self._app_server_lock_fd is not None:
            return True
        self._owner.app_server_lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.secure_dir(self._owner.app_server_lock_file.parent)
        fd = os.open(str(self._owner.app_server_lock_file), os.O_RDWR | os.O_CREAT, SECURE_FILE_MODE)
        if not self.try_lock_fd_nonblocking(fd):
            try:
                os.close(fd)
            except OSError:
                pass
            self.log_app_server_lock_busy()
            return False
        self._app_server_lock_fd = fd
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        except OSError:
            pass
        self.secure_file(self._owner.app_server_lock_file)
        self._app_server_lock_busy_logged_at = 0.0
        self._owner._log(f"app_server_lock_acquired path={self._owner.app_server_lock_file}")
        return True

    def release_lock(self) -> None:
        if self._app_server_lock_fd is None:
            return
        self.unlock_fd(self._app_server_lock_fd)
        try:
            os.close(self._app_server_lock_fd)
        except OSError:
            pass
        self._app_server_lock_fd = None
        self._owner._log(f"app_server_lock_released path={self._owner.app_server_lock_file}")

    def build_codex_app_server_cmd(self, role: str = "app-server") -> list[str]:
        listen = str(getattr(self._owner, "app_server_listen", "stdio://")).strip()
        if not listen:
            listen = "stdio://"
        return ["codex", "app-server", "--listen", listen]

    def secure_file(self, path: Path) -> None:
        try:
            path.chmod(SECURE_FILE_MODE)
        except OSError:
            pass

    def secure_dir(self, path: Path) -> None:
        try:
            path.chmod(SECURE_DIR_MODE)
        except OSError:
            pass

    def harden_sensitive_permissions(self) -> None:
        self.secure_dir(self._owner.logs_dir)
        self.secure_dir(self._owner.state_dir)
        self.secure_dir(self._owner.chat_locks_dir)
        self.secure_file(self._owner.store_file)
        env_file = self._owner.root / ".env"
        if env_file.exists():
            self.secure_file(env_file)
        if self._owner.app_server_state_file.exists():
            self.secure_file(self._owner.app_server_state_file)
        if self._owner.app_server_log_file.exists():
            self.secure_file(self._owner.app_server_log_file)
        if self._owner.app_server_lock_file.exists():
            self.secure_file(self._owner.app_server_lock_file)
        if self._owner.agent_rewriter_state_file.exists():
            self.secure_file(self._owner.agent_rewriter_state_file)
        if self._owner.agent_rewriter_log_file.exists():
            self.secure_file(self._owner.agent_rewriter_log_file)
        if self._owner.agent_rewriter_lock_file.exists():
            self.secure_file(self._owner.agent_rewriter_lock_file)
        if self._owner.agent_rewriter_pid_file.exists():
            self.secure_file(self._owner.agent_rewriter_pid_file)
        self.secure_dir(self._owner.agent_rewriter_workspace)
        if self._owner.codex_pid_file.exists():
            self.secure_file(self._owner.codex_pid_file)
        for log_path in self._owner.logs_dir.glob("*.log"):
            self.secure_file(log_path)

class DaemonServiceAppMixin:

    def _get_app_runtime(self) -> DaemonServiceAppRuntime | None:
        runtime = getattr(self, "_app_runtime_component", None)
        if isinstance(runtime, DaemonServiceAppRuntime):
            return runtime
        return None

    def _init_app_runtime(self, app_runtime: DaemonServiceAppRuntime | None = None) -> None:
        if app_runtime is None:
            app_runtime = DaemonServiceAppRuntime(self)
        self._app_runtime_component = app_runtime
        app_runtime.load_state()

    @property
    def app_proc(self) -> subprocess.Popen[str] | None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return None
        return runtime.app_proc

    @app_proc.setter
    def app_proc(self, value: subprocess.Popen[str] | None) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_proc = value

    @property
    def app_proc_generation(self) -> int:
        runtime = self._get_app_runtime()
        if runtime is None:
            return 0
        return runtime.app_proc_generation

    @app_proc_generation.setter
    def app_proc_generation(self, value: int) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_proc_generation = value

    @property
    def app_json_send_lock(self) -> threading.Lock:
        runtime = self._get_app_runtime()
        if runtime is None:
            return threading.Lock()
        return runtime.app_json_send_lock

    @app_json_send_lock.setter
    def app_json_send_lock(self, value: threading.Lock) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_json_send_lock = value

    @property
    def app_req_lock(self) -> threading.Lock:
        runtime = self._get_app_runtime()
        if runtime is None:
            return threading.Lock()
        return runtime.app_req_lock

    @app_req_lock.setter
    def app_req_lock(self, value: threading.Lock) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_req_lock = value

    @property
    def app_pending_responses(self) -> dict[int, queue.Queue[dict[str, Any]]]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return {}
        return runtime.app_pending_responses

    @app_pending_responses.setter
    def app_pending_responses(self, value: dict[int, queue.Queue[dict[str, Any]]]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_pending_responses = value

    @property
    def app_event_queue(self) -> queue.Queue[dict[str, Any]]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return queue.Queue()
        return runtime.app_event_queue

    @app_event_queue.setter
    def app_event_queue(self, value: queue.Queue[dict[str, Any]]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_event_queue = value

    @property
    def app_next_request_id(self) -> int:
        runtime = self._get_app_runtime()
        if runtime is None:
            return 1
        return runtime.app_next_request_id

    @app_next_request_id.setter
    def app_next_request_id(self, value: int) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_next_request_id = value

    @property
    def app_chat_states(self) -> dict[int, dict[str, Any]]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return {}
        return runtime.app_chat_states

    @app_chat_states.setter
    def app_chat_states(self, value: dict[int, dict[str, Any]]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_chat_states = value

    @property
    def app_thread_to_chat(self) -> dict[str, int]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return {}
        return runtime.app_thread_to_chat

    @app_thread_to_chat.setter
    def app_thread_to_chat(self, value: dict[str, int]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_thread_to_chat = value

    @property
    def app_turn_to_chat(self) -> dict[str, int]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return {}
        return runtime.app_turn_to_chat

    @app_turn_to_chat.setter
    def app_turn_to_chat(self, value: dict[str, int]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_turn_to_chat = value

    @property
    def app_aux_turn_results(self) -> dict[str, dict[str, Any]]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return {}
        return runtime.app_aux_turn_results

    @app_aux_turn_results.setter
    def app_aux_turn_results(self, value: dict[str, dict[str, Any]]) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_aux_turn_results = value

    @property
    def app_last_restart_try_epoch(self) -> float:
        runtime = self._get_app_runtime()
        if runtime is None:
            return 0.0
        return runtime.app_last_restart_try_epoch

    @app_last_restart_try_epoch.setter
    def app_last_restart_try_epoch(self, value: float) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.app_last_restart_try_epoch = value

    def _load_app_server_state(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.load_state()

    def _save_app_server_state(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.save_state()

    def _write_app_server_log(self, prefix: str, line: str) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.write_log(prefix, line)

    def _secure_file(self, path: Path) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.secure_file(path)

    def _secure_dir(self, path: Path) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.secure_dir(path)

    def _harden_sensitive_permissions(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.harden_sensitive_permissions()

    def _get_chat_state(self, chat_id: int) -> dict[str, Any]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return self._new_chat_state()
        return runtime.get_chat_state(chat_id)

    def _sync_codex_runtime_env(
        self,
        *,
        run_id: str,
        mode: str,
        started_at: str,
        resume_target: str,
        session_id: str,
        thread_id: str = "",
    ) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.sync_codex_runtime_env(
            run_id=run_id,
            mode=mode,
            started_at=started_at,
            resume_target=resume_target,
            session_id=session_id,
            thread_id=thread_id,
        )

    def _write_codex_session_meta(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.write_codex_session_meta()

    def _set_runtime_env(self, key: str, value: str) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.set_runtime_env(key, value)

    def _sync_app_server_session_meta(self, active_chat_id: int | None = None) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.sync_app_server_session_meta(active_chat_id=active_chat_id)

    def _read_pid_file(self, path: Path) -> int:
        runtime = self._get_app_runtime()
        if runtime is None:
            return 0
        return runtime.read_pid_file(path)

    def _pid_cmdline(self, pid: int) -> str:
        runtime = self._get_app_runtime()
        if runtime is None:
            return ""
        return runtime.pid_cmdline(pid)

    def _is_codex_app_server_pid(self, pid: int) -> bool:
        runtime = self._get_app_runtime()
        if runtime is None:
            return _is_pid_alive(int(pid))
        return runtime.is_codex_app_server_pid(pid)

    def _try_lock_fd_nonblocking(self, fd: int) -> bool:
        runtime = self._get_app_runtime()
        if runtime is None:
            return True
        return runtime.try_lock_fd_nonblocking(fd)

    def _unlock_fd(self, fd: int) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.unlock_fd(fd)

    def _exclusive_file_lock(self, lock_path: Path, wait_timeout_sec: float | None = None):
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        return runtime.exclusive_file_lock(lock_path, wait_timeout_sec=wait_timeout_sec)

    def _log_app_server_lock_busy(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.log_app_server_lock_busy()

    def _acquire_app_server_lock(self) -> bool:
        runtime = self._get_app_runtime()
        if runtime is None:
            return False
        return runtime.acquire_lock()

    def _release_app_server_lock(self) -> None:
        runtime = self._get_app_runtime()
        if runtime is None:
            return
        runtime.release_lock()

    def _build_codex_app_server_cmd(self, role: str = "app-server") -> list[str]:
        runtime = self._get_app_runtime()
        if runtime is None:
            return [
                "codex",
                "app-server",
                "--listen",
                str(getattr(self, "app_server_listen", "stdio://")) or "stdio://",
            ]
        return runtime.build_codex_app_server_cmd(role=role)

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

