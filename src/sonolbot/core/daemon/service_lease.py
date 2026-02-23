from __future__ import annotations

from pathlib import Path
from sonolbot.core.daemon.runtime_shared import *

class DaemonServiceLeaseRuntime:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.owned_chat_leases: set[int] = set()
        self.chat_lease_busy_logged_at: dict[int, float] = {}
        self.completed_message_ids_recent: dict[int, float] = {}
        self._completed_requeue_log_ts: dict[int, float] = {}

    @property
    def _owner(self) -> Any:
        return self.service


class DaemonServiceLeaseMixin:

    def _get_lease_runtime(self) -> DaemonServiceLeaseRuntime | None:
        runtime = getattr(self, "_lease_runtime_component", None)
        if isinstance(runtime, DaemonServiceLeaseRuntime):
            return runtime
        return None

    def _init_lease_runtime(self, runtime: DaemonServiceLeaseRuntime | None = None) -> None:
        if runtime is None:
            runtime = DaemonServiceLeaseRuntime(self)
        self._lease_runtime_component = runtime

    @property
    def _owned_chat_leases(self) -> set[int]:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return set()
        return runtime.owned_chat_leases

    @_owned_chat_leases.setter
    def _owned_chat_leases(self, value: set[int]) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        runtime.owned_chat_leases = set(value)

    @property
    def _chat_lease_busy_logged_at(self) -> dict[int, float]:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return {}
        return runtime.chat_lease_busy_logged_at

    @_chat_lease_busy_logged_at.setter
    def _chat_lease_busy_logged_at(self, value: dict[int, float]) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        runtime.chat_lease_busy_logged_at = value

    @property
    def completed_message_ids_recent(self) -> dict[int, float]:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return {}
        return runtime.completed_message_ids_recent

    @completed_message_ids_recent.setter
    def completed_message_ids_recent(self, value: dict[int, float]) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        runtime.completed_message_ids_recent = value

    @property
    def _completed_requeue_log_ts(self) -> dict[int, float]:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return {}
        return runtime._completed_requeue_log_ts

    @_completed_requeue_log_ts.setter
    def _completed_requeue_log_ts(self, value: dict[int, float]) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        runtime._completed_requeue_log_ts = value

    def _remember_completed_message_ids(self, message_ids: set[int] | list[int]) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        now_epoch = time.time()
        ttl = float(self.completed_message_ttl_sec)
        if ttl <= 0:
            return
        for raw_msg_id in message_ids:
            try:
                msg_id = int(raw_msg_id)
            except Exception:
                continue
            if msg_id <= 0:
                continue
            runtime.completed_message_ids_recent[msg_id] = now_epoch

    def _is_message_recently_completed(self, message_id: int, now_epoch: float | None = None) -> bool:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return False
        try:
            msg_id = int(message_id)
        except Exception:
            return False
        if msg_id <= 0:
            return False
        ttl = float(self.completed_message_ttl_sec)
        if ttl <= 0:
            return False
        now = float(now_epoch) if now_epoch is not None else time.time()
        last_epoch = float(runtime.completed_message_ids_recent.get(msg_id) or 0.0)
        if last_epoch <= 0.0:
            return False
        return (now - last_epoch) <= ttl

    def _recently_completed_message_age_sec(self, message_id: int, now_epoch: float | None = None) -> float:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return -1.0
        try:
            msg_id = int(message_id)
        except Exception:
            return -1.0
        if msg_id <= 0:
            return -1.0
        now = float(now_epoch) if now_epoch is not None else time.time()
        last_epoch = float(runtime.completed_message_ids_recent.get(msg_id) or 0.0)
        if last_epoch <= 0.0:
            return -1.0
        return max(0.0, now - last_epoch)

    def _log_recently_completed_drop(self, chat_id: int, message_id: int, age_sec: float) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        now = time.time()
        try:
            msg_id = int(message_id)
        except Exception:
            msg_id = 0
        last_ts = float(runtime._completed_requeue_log_ts.get(msg_id) or 0.0)
        if (now - last_ts) < 1.0:
            return
        runtime._completed_requeue_log_ts[msg_id] = now
        self._log(
            f"turn_start_completed_cache_filter chat_id={chat_id} message_id={msg_id} age={age_sec:.1f}s"
        )

    def _prune_completed_message_cache(self) -> None:
        runtime = self._get_lease_runtime()
        if runtime is None:
            return
        ttl = float(self.completed_message_ttl_sec)
        if ttl <= 0:
            runtime.completed_message_ids_recent.clear()
            runtime._completed_requeue_log_ts.clear()
            return
        now = time.time()
        expire_before = now - ttl
        for msg_id in list(runtime.completed_message_ids_recent.keys()):
            if float(runtime.completed_message_ids_recent.get(msg_id) or 0.0) < expire_before:
                runtime.completed_message_ids_recent.pop(msg_id, None)
                runtime._completed_requeue_log_ts.pop(msg_id, None)


    def _chat_lease_path(self, chat_id: int) -> Path:
        return self.chat_locks_dir / f"chat_{int(chat_id)}.json"

    def _chat_lease_lock_path(self, chat_id: int) -> Path:
        return self.chat_locks_dir / f"chat_{int(chat_id)}.lock"

    def _load_chat_lease_unlocked(self, chat_id: int) -> dict[str, Any] | None:
        path = self._chat_lease_path(chat_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            return None
        return None

    def _save_chat_lease_unlocked(self, chat_id: int, payload: dict[str, Any]) -> None:
        path = self._chat_lease_path(chat_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._secure_dir(path.parent)
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._secure_file(tmp)
            os.replace(tmp, path)
            self._secure_file(path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _delete_chat_lease_unlocked(self, chat_id: int) -> None:
        path = self._chat_lease_path(chat_id)
        if not path.exists():
            return
        try:
            path.unlink()
        except OSError:
            pass

    def _chat_lease_status(self, lease: dict[str, Any], now_epoch: float) -> tuple[bool, str]:
        try:
            expires_at = float(lease.get("expires_at") or 0.0)
        except Exception:
            expires_at = 0.0
        owner_pid = int(lease.get("owner_pid") or 0)
        if expires_at <= now_epoch:
            return False, "expired"
        if owner_pid <= 0 or not _is_pid_alive(owner_pid):
            return False, "owner_dead"
        return True, "active"

    def _log_chat_lease_busy(self, chat_id: int, owner_pid: int, expires_at: float) -> None:
        now_epoch = time.time()
        last = float(self._chat_lease_busy_logged_at.get(chat_id) or 0.0)
        if (now_epoch - last) < max(5.0, float(self.poll_interval_sec)):
            return
        self._chat_lease_busy_logged_at[chat_id] = now_epoch
        remain = max(0.0, expires_at - now_epoch)
        self._log(
            f"chat_lease_busy chat_id={chat_id} owner_pid={owner_pid or '-'} "
            f"remaining={remain:.1f}s"
        )

    def _chat_lease_try_acquire(self, chat_id: int, message_ids: set[int]) -> bool:
        msg_ids = sorted(int(v) for v in message_ids if int(v) > 0)
        now_epoch = time.time()
        lock_path = self._chat_lease_lock_path(chat_id)
        try:
            with self._exclusive_file_lock(lock_path):
                lease = self._load_chat_lease_unlocked(chat_id)
                if isinstance(lease, dict):
                    valid, _ = self._chat_lease_status(lease, now_epoch)
                    owner_pid = int(lease.get("owner_pid") or 0)
                    expires_at = float(lease.get("expires_at") or 0.0)
                    if valid and owner_pid != os.getpid():
                        self._log_chat_lease_busy(chat_id, owner_pid, expires_at)
                        return False
                    if not valid:
                        self._delete_chat_lease_unlocked(chat_id)
                        self._log(
                            f"chat_lease_recovered chat_id={chat_id} stale_reason=expired_or_owner_dead"
                        )

                payload = {
                    "chat_id": int(chat_id),
                    "owner_pid": int(os.getpid()),
                    "app_server_pid": int(self.app_proc.pid) if self._app_is_running() and self.app_proc else 0,
                    "turn_id": "",
                    "message_ids": msg_ids,
                    "acquired_at": now_epoch,
                    "updated_at": now_epoch,
                    "expires_at": now_epoch + float(self.chat_lease_ttl_sec),
                }
                self._save_chat_lease_unlocked(chat_id, payload)
                self._owned_chat_leases.add(int(chat_id))
                self._chat_lease_busy_logged_at.pop(int(chat_id), None)
                self._log(f"chat_lease_acquired chat_id={chat_id} messages={len(msg_ids)}")
                return True
        except TimeoutError:
            self._log(f"WARN: chat_lease_lock_timeout chat_id={chat_id}")
            return False
        except Exception as exc:
            self._log(f"WARN: chat_lease_acquire_failed chat_id={chat_id}: {exc}")
            return False

    def _chat_lease_touch(
        self,
        chat_id: int,
        *,
        turn_id: str | None = None,
        message_ids: set[int] | None = None,
    ) -> bool:
        now_epoch = time.time()
        lock_path = self._chat_lease_lock_path(chat_id)
        try:
            with self._exclusive_file_lock(lock_path):
                lease = self._load_chat_lease_unlocked(chat_id)
                if not isinstance(lease, dict):
                    return False
                owner_pid = int(lease.get("owner_pid") or 0)
                if owner_pid != os.getpid():
                    return False
                lease["app_server_pid"] = int(self.app_proc.pid) if self._app_is_running() and self.app_proc else 0
                lease["updated_at"] = now_epoch
                lease["expires_at"] = now_epoch + float(self.chat_lease_ttl_sec)
                if turn_id is not None:
                    lease["turn_id"] = str(turn_id or "")
                if message_ids is not None:
                    lease["message_ids"] = sorted(int(v) for v in message_ids if int(v) > 0)
                self._save_chat_lease_unlocked(chat_id, lease)
                return True
        except TimeoutError:
            self._log(f"WARN: chat_lease_touch_timeout chat_id={chat_id}")
            return False
        except Exception as exc:
            self._log(f"WARN: chat_lease_touch_failed chat_id={chat_id}: {exc}")
            return False

    def _chat_lease_release(self, chat_id: int, reason: str) -> None:
        lock_path = self._chat_lease_lock_path(chat_id)
        released = False
        try:
            with self._exclusive_file_lock(lock_path):
                lease = self._load_chat_lease_unlocked(chat_id)
                if isinstance(lease, dict):
                    valid, _ = self._chat_lease_status(lease, time.time())
                    owner_pid = int(lease.get("owner_pid") or 0)
                    if valid and owner_pid != os.getpid():
                        return
                self._delete_chat_lease_unlocked(chat_id)
                released = True
        except TimeoutError:
            self._log(f"WARN: chat_lease_release_timeout chat_id={chat_id} reason={reason}")
            return
        except Exception as exc:
            self._log(f"WARN: chat_lease_release_failed chat_id={chat_id} reason={reason}: {exc}")
            return
        finally:
            self._owned_chat_leases.discard(int(chat_id))
            self._chat_lease_busy_logged_at.pop(int(chat_id), None)
        if released:
            self._log(f"chat_lease_released chat_id={chat_id} reason={reason}")

    def _release_owned_chat_leases(self, reason: str) -> None:
        for chat_id in sorted(self._owned_chat_leases.copy()):
            self._chat_lease_release(chat_id, reason=reason)

    def _has_any_active_chat_lease(self) -> bool:
        if not self.chat_locks_dir.exists():
            return False
        now_epoch = time.time()
        for path in self.chat_locks_dir.glob("chat_*.json"):
            chat_id = 0
            m = re.search(r"chat_(\d+)\.json$", path.name)
            if m:
                try:
                    chat_id = int(m.group(1))
                except Exception:
                    chat_id = 0
            try:
                lease = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(lease, dict):
                continue
            valid, _ = self._chat_lease_status(lease, now_epoch)
            if valid:
                return True
            if chat_id > 0:
                self._chat_lease_release(chat_id, reason="stale_cleanup")
        return False


