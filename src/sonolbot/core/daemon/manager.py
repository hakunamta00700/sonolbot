"Root multi-bot manager."
from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *
from sonolbot.core.daemon import manager_utils as _manager_utils

class MultiBotManager:
    """Root daemon manager that spawns one bot worker per configured token."""

    def __init__(self) -> None:
        self.root = PROJECT_ROOT
        self.logs_dir = Path(os.getenv("LOGS_DIR", str(self.root / "logs"))).resolve()
        self.pid_file = Path(
            os.getenv("DAEMON_PID_FILE", str(self.root / ".daemon_service.pid"))
        ).resolve()
        self.lock_file = Path(
            os.getenv("DAEMON_LOCK_FILE", str(self.pid_file.with_suffix(".lock")))
        ).resolve()
        self.poll_interval_sec = max(1, int(os.getenv("DAEMON_POLL_INTERVAL_SEC", "1")))
        self.log_retention_days = max(1, int(os.getenv("LOG_RETENTION_DAYS", "7")))
        self.workspace_root = Path(
            os.getenv("SONOLBOT_BOT_WORKSPACES_DIR", str(self.root / DEFAULT_BOT_WORKSPACE_DIRNAME))
        ).resolve()
        self.config_path = default_config_path(self.root)
        self.python_bin = self._detect_python_bin()
        self.stop_requested = False
        self.workers: dict[str, dict[str, Any]] = {}
        self.worker_restart_state: dict[str, dict[str, Any]] = {}
        self.worker_restart_base_sec = self._env_float(
            "DAEMON_WORKER_RESTART_BASE_SEC",
            DEFAULT_WORKER_RESTART_BASE_SEC,
            minimum=1.0,
        )
        self.worker_restart_max_sec = self._env_float(
            "DAEMON_WORKER_RESTART_MAX_SEC",
            DEFAULT_WORKER_RESTART_MAX_SEC,
            minimum=5.0,
        )
        self.worker_stable_reset_sec = self._env_float(
            "DAEMON_WORKER_STABLE_RESET_SEC",
            DEFAULT_WORKER_STABLE_RESET_SEC,
            minimum=5.0,
        )
        self._process_lock: _ProcessFileLock | None = None
        self.env = os.environ.copy()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def _detect_python_bin(self) -> str:
        venv_py = self.root / ".venv" / "bin" / "python"
        if venv_py.exists():
            return str(venv_py)
        return sys.executable

    def _daily_log_path(self) -> Path:
        return self.logs_dir / f"daemon-{datetime.now().strftime('%Y-%m-%d')}.log"

    def _env_float(self, name: str, default: float, minimum: float = 0.0) -> float:
        return _manager_utils.env_float(name, default, minimum=minimum)

    def _log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [manager] {message}\n"
        log_path = self._daily_log_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def _cleanup_logs(self) -> None:
        cutoff = datetime.now().date() - timedelta(days=self.log_retention_days - 1)
        for path in self.logs_dir.glob("*.log"):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
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

    def _acquire_lock(self) -> None:
        if self._process_lock is None:
            self._process_lock = _ProcessFileLock(
                lock_file=self.lock_file,
                pid_file=self.pid_file,
                owner_label="Daemon manager",
            )
        self._process_lock.acquire()

    def _release_lock(self) -> None:
        if self._process_lock is not None:
            self._process_lock.release()
            self._process_lock = None

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self._log(f"Signal received: {signum}")
        self.stop_requested = True

    @staticmethod
    def _safe_bot_key(bot_id: str) -> str:
        return _manager_utils.safe_bot_key(bot_id)

    def _workspace_for_bot(self, bot_id: str) -> Path:
        return (self.workspace_root / self._safe_bot_key(bot_id)).resolve()

    def _load_active_bots(self) -> list[dict[str, Any]]:
        cfg = load_bots_config(self.config_path)
        normalized_allowed = _manager_utils.normalize_allowed_users(
            cfg.get("allowed_users_global")
        )
        return _manager_utils.active_bots(cfg, normalized_allowed)

    def _worker_env(self, bot: dict[str, Any], workspace: Path) -> dict[str, str]:
        rewriter_tmp_root = Path(
            os.getenv("DAEMON_AGENT_REWRITER_TMP_ROOT", DEFAULT_AGENT_REWRITER_TMP_ROOT)
        ).expanduser().resolve()
        env = _manager_utils.build_worker_env(
            bot=bot,
            workspace=workspace,
            config_path=self.config_path,
            base_env=self.env,
            rewriter_tmp_root=rewriter_tmp_root,
        )
        state_dir = workspace / "state"
        for path in (
            workspace / "logs",
            workspace / "tasks",
            workspace / "messages",
            state_dir,
            workspace / "results",
        ):
            path.mkdir(parents=True, exist_ok=True)
        rewriter_workspace = Path(env["DAEMON_AGENT_REWRITER_WORKSPACE"])
        try:
            rewriter_workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log(
                f"WARN: failed to create tmp rewriter workspace bot_id={bot.get('bot_id')} "
                f"path={rewriter_workspace}: {exc}; fallback to state dir"
            )
            env["DAEMON_AGENT_REWRITER_WORKSPACE"] = str(state_dir / "agent-rewriter-workspace")
        return env

    def _spawn_worker(self, bot: dict[str, Any]) -> None:
        bot_id = str(bot["bot_id"])
        workspace = self._workspace_for_bot(bot_id)
        env = self._worker_env(bot, workspace)
        cmd = [self.python_bin, str(CORE_ROOT / "daemon_service.py")]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.root),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=(os.name != "nt"),
            )
        except Exception as exc:
            self._log(f"ERROR: failed to spawn worker bot_id={bot_id}: {exc}")
            return
        self.workers[bot_id] = {
            "proc": proc,
            "workspace": workspace,
            "token": str(bot["token"]),
            "started_at": time.time(),
        }
        state = self.worker_restart_state.setdefault(bot_id, {})
        state["last_spawn_at"] = time.time()
        self._log(f"worker started bot_id={bot_id} pid={proc.pid} workspace={workspace}")

    def _stop_worker(self, bot_id: str, reason: str) -> None:
        slot = self.workers.pop(bot_id, None)
        if not slot:
            return
        proc = slot.get("proc")
        if not isinstance(proc, subprocess.Popen):
            return
        self._log(f"worker stopping bot_id={bot_id} pid={proc.pid} reason={reason}")
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _register_worker_exit(self, bot_id: str, rc: int, runtime_sec: float) -> None:
        state = self.worker_restart_state.setdefault(bot_id, {})
        fail_count, next_start_at, backoff_sec, updated_state = _manager_utils.update_restart_state(
            state,
            exit_code=int(rc),
            runtime_sec=runtime_sec,
            stable_reset_sec=self.worker_stable_reset_sec,
            base_backoff_sec=self.worker_restart_base_sec,
            max_backoff_sec=self.worker_restart_max_sec,
        )
        self.worker_restart_state[bot_id] = updated_state
        if backoff_sec > 0:
            self._log(
                f"worker restart delayed bot_id={bot_id} rc={rc} runtime={runtime_sec:.1f}s "
                f"backoff={backoff_sec:.1f}s failures={fail_count}"
            )

    def _can_start_worker_now(self, bot_id: str) -> bool:
        state = self.worker_restart_state.get(bot_id) or {}
        now = time.time()
        can_start, remaining, should_log = _manager_utils.can_start_worker_now(
            state,
            now_epoch=now,
            poll_interval_sec=self.poll_interval_sec,
        )
        if should_log:
            state["last_skip_log_at"] = now
            self.worker_restart_state[bot_id] = state
            self._log(
                f"worker start skipped due to backoff bot_id={bot_id} "
                f"remaining={remaining:.1f}s"
            )
        return can_start

    def _sync_workers(self) -> None:
        active = self._load_active_bots()
        active_map = {str(row["bot_id"]): row for row in active}

        # Stop removed/inactive workers.
        for bot_id in list(self.workers.keys()):
            if bot_id not in active_map:
                self._stop_worker(bot_id, "inactive_or_removed")
                self.worker_restart_state.pop(bot_id, None)

        # Reap dead workers.
        for bot_id, slot in list(self.workers.items()):
            proc = slot.get("proc")
            if not isinstance(proc, subprocess.Popen):
                continue
            rc = proc.poll()
            if rc is None:
                started_at = float(slot.get("started_at") or 0.0)
                if started_at > 0 and (time.time() - started_at) >= self.worker_stable_reset_sec:
                    state = self.worker_restart_state.get(bot_id)
                    if state and int(state.get("fail_count") or 0) > 0:
                        state["fail_count"] = 0
                        state["next_start_at"] = 0.0
                        self.worker_restart_state[bot_id] = state
                continue
            self.workers.pop(bot_id, None)
            started_at = float(slot.get("started_at") or 0.0)
            runtime_sec = max(0.0, time.time() - started_at) if started_at > 0 else 0.0
            self._log(f"worker exited bot_id={bot_id} rc={rc} runtime={runtime_sec:.1f}s")
            self._register_worker_exit(bot_id=bot_id, rc=int(rc), runtime_sec=runtime_sec)

        # Start missing workers.
        for bot_id, bot in active_map.items():
            if bot_id in self.workers:
                # Token changed: restart worker with new env.
                old_token = str(self.workers[bot_id].get("token") or "")
                new_token = str(bot.get("token") or "")
                if old_token != new_token:
                    self._stop_worker(bot_id, "token_changed")
                    if not self._can_start_worker_now(bot_id):
                        continue
                    self._spawn_worker(bot)
                continue
            if not self._can_start_worker_now(bot_id):
                continue
            self._spawn_worker(bot)

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

        migrated, detail = migrate_legacy_env_if_needed(self.root, self.config_path)
        if migrated:
            self._log(f"legacy config migrated: {detail}")
        else:
            self._log(f"legacy migration skipped: {detail}")

        self._log(
            f"manager started pid={os.getpid()} poll={self.poll_interval_sec}s "
            f"config={self.config_path} workspace_root={self.workspace_root}"
        )
        try:
            while not self.stop_requested:
                self._cleanup_logs()
                self._sync_workers()
                time.sleep(self.poll_interval_sec)
        finally:
            for bot_id in list(self.workers.keys()):
                self._stop_worker(bot_id, "manager_shutdown")
            self._release_lock()
            self._log("manager stopped")
        return 0


