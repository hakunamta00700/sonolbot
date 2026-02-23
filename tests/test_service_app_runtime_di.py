from __future__ import annotations

import json
import os
import sys
import tempfile
import types
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


def _import_service_app():
    try:
        from sonolbot.core.daemon.service_app import DaemonServiceAppMixin, DaemonServiceAppRuntime

        return DaemonServiceAppMixin, DaemonServiceAppRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_app import DaemonServiceAppMixin, DaemonServiceAppRuntime

            return DaemonServiceAppMixin, DaemonServiceAppRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceAppMixin, DaemonServiceAppRuntime, _IMPORT_ERROR = _import_service_app()

if DaemonServiceAppMixin is None or DaemonServiceAppRuntime is None:

    @unittest.skip("daemon service app runtime dependency unavailable")
    class TestDaemonServiceAppRuntimeDependency(unittest.TestCase):
        def test_service_app_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)

else:

    class _FakeServiceForAppRuntime(DaemonServiceAppMixin):
        """Minimal service fixture that exposes only fields used by app runtime mixin tests."""

        def __init__(self, root: Path) -> None:
            self.app_server_state_file = root / "app-server-state.json"
            self.store_file = root / "telegram_messages.json"
            self.app_server_log_file = root / "codex-app-server.log"
            self.app_server_lock_file = root / "app-server.lock"
            self.codex_pid_file = root / "codex.pid"
            self.codex_session_meta_file = root / "codex-session-current.json"
            self.app_server_listen = "stdio://"
            self.codex_model = "test-model"
            self.codex_reasoning_effort = "medium"
            self.codex_cli_version = "unit-test"
            self.codex_run_meta: dict[str, object] | None = None
            self.env: dict[str, str] = {}
            self._log_messages: list[str] = []

        def _new_chat_state(self) -> dict[str, object]:
            return {
                "thread_id": "",
                "app_generation": 0,
                "queued_messages": [],
                "active_message_ids": set(),
                "active_task_ids": set(),
                "delta_text": "",
                "final_text": "",
                "last_agent_message_sent": "",
                "last_agent_message_raw": "",
                "last_progress_len": 0,
                "last_progress_sent_at": 0.0,
                "last_turn_started_at": 0.0,
                "last_lease_heartbeat_at": 0.0,
            }

        def _log(self, message: str) -> None:
            self._log_messages.append(message)


    class TestDaemonServiceAppRuntimeInjection(unittest.TestCase):
        def test_init_app_runtime_loads_state(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                service = _FakeServiceForAppRuntime(root)
                payload = {
                    "version": 1,
                    "sessions": {
                        "101": {"thread_id": "thread-loaded"},
                    },
                }
                service.app_server_state_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

                service._init_app_runtime()

                state = service._get_chat_state(101)
                self.assertEqual(state.get("thread_id"), "thread-loaded")
                self.assertEqual(list(service.app_chat_states.keys()), [101])

        def test_injected_runtime_instance_is_used(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                service = _FakeServiceForAppRuntime(root)
                runtime = DaemonServiceAppRuntime(service)

                service._init_app_runtime(runtime)

                self.assertIs(service._get_app_runtime(), runtime)
                self.assertIs(service.app_proc, None)
                service.app_proc = object()  # type: ignore[assignment]
                self.assertIs(service.app_proc, runtime.app_proc)
                self.assertIs(service._get_app_runtime(), runtime)

        def test_init_app_runtime_rejects_invalid_runtime(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForAppRuntime(Path(td))

                with self.assertRaisesRegex(
                    TypeError,
                    "app_runtime must be DaemonServiceAppRuntime",
                ):
                    service._init_app_runtime(app_runtime=object())  # type: ignore[arg-type]

        def test_save_app_server_state_roundtrip(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                service = _FakeServiceForAppRuntime(root)
                service._init_app_runtime()

                state = service._get_chat_state(202)
                state["thread_id"] = "thread-saved"
                service.app_chat_states = {202: state}

                service._save_app_server_state()

                loaded = json.loads(service.app_server_state_file.read_text(encoding="utf-8"))
                sessions = loaded.get("sessions", {})
                self.assertEqual(sessions, {"202": {"thread_id": "thread-saved"}})

        def test_set_runtime_env_updates_service_and_process_env(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                service = _FakeServiceForAppRuntime(root)
                service._init_app_runtime()

                original = os.environ.get("SONOLBOT_UNIT_TEST_ENV")
                try:
                    service._set_runtime_env("SONOLBOT_UNIT_TEST_ENV", "1")
                    self.assertEqual(service.env.get("SONOLBOT_UNIT_TEST_ENV"), "1")
                    self.assertEqual(os.environ.get("SONOLBOT_UNIT_TEST_ENV"), "1")
                finally:
                    if original is None:
                        os.environ.pop("SONOLBOT_UNIT_TEST_ENV", None)
                    else:
                        os.environ["SONOLBOT_UNIT_TEST_ENV"] = original
