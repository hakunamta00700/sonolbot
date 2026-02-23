from __future__ import annotations

import errno
import os
from pathlib import Path
from sonolbot.core.daemon.constants import SECURE_FILE_MODE

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore

try:
    import msvcrt  # type: ignore
except Exception:  # pragma: no cover
    msvcrt = None  # type: ignore


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class _ProcessFileLock:
    """Cross-platform process lock backed by a lock file and a pid file."""

    def __init__(self, lock_file: Path, pid_file: Path, owner_label: str) -> None:
        self.lock_file = lock_file.resolve()
        self.pid_file = pid_file.resolve()
        self.owner_label = owner_label
        self._fd: int | None = None

    def _try_lock_fd(self, fd: int) -> bool:
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    return False
                raise
        if msvcrt is not None:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        # Best-effort fallback if OS-level non-blocking lock APIs are unavailable.
        if self.pid_file.exists():
            return False
        return True

    def acquire(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, SECURE_FILE_MODE)
            if self._try_lock_fd(fd):
                self._fd = fd
                try:
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{os.getpid()}\\n".encode("utf-8"))
                except OSError:
                    pass
                self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
                return
            os.close(fd)
            existing = 0
            try:
                existing = int(self.pid_file.read_text(encoding="utf-8").strip())
            except Exception:
                existing = 0
            if _is_pid_alive(existing):
                raise RuntimeError(f"{self.owner_label} already running (pid={existing})")
            try:
                if self.pid_file.exists():
                    self.pid_file.unlink()
                if attempt == 0 and self.lock_file.exists():
                    self.lock_file.unlink()
                    continue
            except OSError:
                pass
            raise RuntimeError(f"{self.owner_label} lock is busy: {self.lock_file}")

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            current_pid = 0
            try:
                current_pid = int(self.pid_file.read_text(encoding="utf-8").strip())
            except Exception:
                current_pid = 0
            if current_pid == os.getpid() and self.pid_file.exists():
                self.pid_file.unlink()
        except OSError:
            pass

        try:
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

__all__ = ["_is_pid_alive", "_ProcessFileLock"]
