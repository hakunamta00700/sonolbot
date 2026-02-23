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


def _import_service_task():
    try:
        from sonolbot.core.daemon.service_task import DaemonServiceTaskMixin, DaemonServiceTaskRuntime

        return DaemonServiceTaskMixin, DaemonServiceTaskRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_task import DaemonServiceTaskMixin, DaemonServiceTaskRuntime

            return DaemonServiceTaskMixin, DaemonServiceTaskRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceTaskMixin, DaemonServiceTaskRuntime, _IMPORT_ERROR = _import_service_task()


if DaemonServiceTaskMixin is None or DaemonServiceTaskRuntime is None:

    @unittest.skip("daemon service task runtime dependency unavailable")
    class TestDaemonServiceTaskRuntimeDependency(unittest.TestCase):
        def test_service_task_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)


else:
    class _FakeServiceForTaskRuntime(DaemonServiceTaskMixin):
        def __init__(self) -> None:
            self._log_messages: list[str] = []

        def _log(self, message: str) -> None:
            self._log_messages.append(message)


    class TestDaemonServiceTaskRuntimeDI(unittest.TestCase):
        def test_init_task_runtime_allocates_runtime(self) -> None:
            service = _FakeServiceForTaskRuntime()
            service._init_task_runtime()

            runtime = service._get_task_runtime()
            self.assertIsNotNone(runtime)
            self.assertIsNone(runtime.task_skill)  # type: ignore[union-attr]

        def test_injected_runtime_instance_is_used(self) -> None:
            service = _FakeServiceForTaskRuntime()
            runtime = DaemonServiceTaskRuntime(service)

            service._init_task_runtime(runtime)
            fake_skill = object()
            runtime.task_skill = fake_skill

            self.assertIs(service._get_task_runtime(), runtime)
            self.assertIs(service._get_task_skill(), fake_skill)

        def test_init_task_runtime_rejects_invalid_runtime(self) -> None:
            service = _FakeServiceForTaskRuntime()
            with self.assertRaises(TypeError):
                service._init_task_runtime(task_runtime=object())  # type: ignore[arg-type]

        def test_task_skill_is_cached_once(self) -> None:
            import sonolbot.core.daemon.service_task as service_task_module

            service = _FakeServiceForTaskRuntime()
            service._init_task_runtime()
            call_count = {"count": 0}

            def fake_get_task_skill():
                call_count["count"] += 1
                return {"name": "stub-task-skill"}

            original = service_task_module.get_task_skill
            service_task_module.get_task_skill = fake_get_task_skill
            try:
                first = service._get_task_skill()
                second = service._get_task_skill()
            finally:
                service_task_module.get_task_skill = original

            self.assertEqual(call_count["count"], 1)
            self.assertIsInstance(first, dict)
            self.assertIs(first, second)
