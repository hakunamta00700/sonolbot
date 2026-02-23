from __future__ import annotations

import sys
import tempfile
import types
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _ensure_fake_dotenv() -> None:
    if "dotenv" in sys.modules:
        return
    fake = types.ModuleType("dotenv")

    def _load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False

    fake.load_dotenv = _load_dotenv
    sys.modules["dotenv"] = fake


def _import_service_lease():
    try:
        from sonolbot.core.daemon.service_lease import DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime

        return DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_lease import DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime

            return DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceLeaseMixin, DaemonServiceLeaseRuntime, _IMPORT_ERROR = _import_service_lease()


if DaemonServiceLeaseMixin is None or DaemonServiceLeaseRuntime is None:

    @unittest.skip("daemon service lease runtime dependency unavailable")
    class TestDaemonServiceLeaseRuntimeDependency(unittest.TestCase):
        def test_service_lease_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)


else:

    class _FakeServiceForLeaseRuntime(DaemonServiceLeaseMixin):
        def __init__(self, root: Path) -> None:
            self.chat_locks_dir = root / "chat_locks"
            self.chat_locks_dir.mkdir(parents=True, exist_ok=True)
            self.chat_lease_ttl_sec = 1.5
            self.completed_message_ttl_sec = 2.5
            self.poll_interval_sec = 1
            self.app_proc = None
            self._log_messages: list[str] = []

        def _log(self, message: str) -> None:
            self._log_messages.append(message)

        def _app_is_running(self) -> bool:
            return False

    class TestDaemonServiceLeaseRuntimeDI(unittest.TestCase):
        def test_init_lease_runtime_allocates_runtime(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForLeaseRuntime(Path(td))
                service._init_lease_runtime()

                runtime = service._get_lease_runtime()
                self.assertIsNotNone(runtime)
                self.assertEqual(service._owned_chat_leases, set())
                self.assertEqual(service._chat_lease_busy_logged_at, {})
                self.assertEqual(service.completed_message_ids_recent, {})
                self.assertEqual(service._completed_requeue_log_ts, {})

        def test_injected_runtime_instance_is_used(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForLeaseRuntime(Path(td))
                runtime = DaemonServiceLeaseRuntime(service)
                service._init_lease_runtime(runtime)

                self.assertIs(service._get_lease_runtime(), runtime)
                service._owned_chat_leases.add(101)
                self.assertIn(101, runtime.owned_chat_leases)
                service._chat_lease_busy_logged_at[101] = 12.3
                self.assertEqual(runtime.chat_lease_busy_logged_at, {101: 12.3})

        def test_init_lease_runtime_rejects_invalid_runtime(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForLeaseRuntime(Path(td))

                with self.assertRaisesRegex(
                    TypeError,
                    "lease_runtime must be DaemonServiceLeaseRuntime",
                ):
                    service._init_lease_runtime(runtime=object())  # type: ignore[arg-type]

        def test_completed_message_cache_lifecycle(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForLeaseRuntime(Path(td))
                service._init_lease_runtime()
                service.completed_message_ttl_sec = 60.0

                service._remember_completed_message_ids({101, 202})
                self.assertTrue(service._is_message_recently_completed(101))
                self.assertTrue(service._is_message_recently_completed(202))

                self.assertGreaterEqual(service._recently_completed_message_age_sec(101), 0.0)
                self.assertIn(101, service.completed_message_ids_recent)
                self.assertIn(202, service.completed_message_ids_recent)

                runtime = service._get_lease_runtime()
                self.assertIsNotNone(runtime)
                assert runtime is not None
                now = time.time()
                runtime.completed_message_ids_recent = {101: now - 1200.0, 202: now}
                service._prune_completed_message_cache()

                self.assertNotIn(101, service.completed_message_ids_recent)
                self.assertIn(202, service.completed_message_ids_recent)

        def test_recently_completed_drop_is_throttled(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForLeaseRuntime(Path(td))
                service._init_lease_runtime()
                runtime = service._get_lease_runtime()
                self.assertIsNotNone(runtime)
                assert runtime is not None
                runtime.completed_message_ids_recent[99] = time.time() - 1.0

                service._log_recently_completed_drop(chat_id=1, message_id=99, age_sec=1.2)
                service._log_recently_completed_drop(chat_id=1, message_id=99, age_sec=1.2)

                self.assertEqual(len(service._log_messages), 1)
                self.assertIn("turn_start_completed_cache_filter", service._log_messages[0])

