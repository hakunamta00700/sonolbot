from __future__ import annotations

import sys
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


def _import_service_telegram():
    try:
        from sonolbot.core.daemon.service_telegram import (
            DaemonServiceTelegramMixin,
            DaemonServiceTelegramRuntime,
        )

        return DaemonServiceTelegramMixin, DaemonServiceTelegramRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_telegram import (
                DaemonServiceTelegramMixin,
                DaemonServiceTelegramRuntime,
            )

            return DaemonServiceTelegramMixin, DaemonServiceTelegramRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceTelegramMixin, DaemonServiceTelegramRuntime, _IMPORT_ERROR = _import_service_telegram()


if DaemonServiceTelegramMixin is None or DaemonServiceTelegramRuntime is None:

    @unittest.skip("daemon service telegram runtime dependency unavailable")
    class TestDaemonServiceTelegramRuntimeDependency(unittest.TestCase):
        def test_service_telegram_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)


else:
    class _FakeServiceForTelegramRuntime(DaemonServiceTelegramMixin):
        def __init__(self) -> None:
            self._log_messages: list[str] = []

        def _log(self, message: str) -> None:
            self._log_messages.append(message)


    class TestDaemonServiceTelegramRuntimeDI(unittest.TestCase):
        def test_init_telegram_runtime_allocates_runtime(self) -> None:
            service = _FakeServiceForTelegramRuntime()
            service._init_telegram_runtime()

            runtime = service._get_telegram_runtime()
            self.assertIsNotNone(runtime)
            self.assertIsNone(runtime.telegram_runtime)  # type: ignore[union-attr]
            self.assertIsNone(runtime.telegram_skill)  # type: ignore[union-attr]

        def test_injected_runtime_instance_is_used(self) -> None:
            service = _FakeServiceForTelegramRuntime()
            runtime = DaemonServiceTelegramRuntime(service)
            service._init_telegram_runtime(runtime)
            runtime.telegram_runtime = {"runtime": "injected"}
            runtime.telegram_skill = {"skill": "injected"}

            resolved_runtime, resolved_skill = service._get_telegram_runtime_skill()
            self.assertEqual(resolved_runtime, {"runtime": "injected"})
            self.assertEqual(resolved_skill, {"skill": "injected"})
            self.assertIs(service._get_telegram_runtime(), runtime)

        def test_telegram_runtime_is_cached_once(self) -> None:
            import sonolbot.core.daemon.service_telegram as telegram_module

            service = _FakeServiceForTelegramRuntime()
            service._init_telegram_runtime()
            counts = {"build": 0, "skill": 0}

            def fake_build():
                counts["build"] += 1
                return {"runtime": "mock"}

            def fake_get_skill():
                counts["skill"] += 1
                return {"skill": "mock"}

            original_build = telegram_module.build_telegram_runtime
            original_get_skill = telegram_module.get_telegram_skill
            telegram_module.build_telegram_runtime = fake_build
            telegram_module.get_telegram_skill = fake_get_skill
            try:
                first = service._get_telegram_runtime_skill()
                second = service._get_telegram_runtime_skill()
            finally:
                telegram_module.build_telegram_runtime = original_build
                telegram_module.get_telegram_skill = original_get_skill

            self.assertEqual(counts["build"], 1)
            self.assertEqual(counts["skill"], 1)
            self.assertEqual(first, second)
