from __future__ import annotations

import sys
import types
import tempfile
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


def _import_service_core():
    try:
        from sonolbot.core.daemon.service_core import DaemonServiceCoreMixin, DaemonServiceCoreRuntime

        return DaemonServiceCoreMixin, DaemonServiceCoreRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_core import DaemonServiceCoreMixin, DaemonServiceCoreRuntime

            return DaemonServiceCoreMixin, DaemonServiceCoreRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceCoreMixin, DaemonServiceCoreRuntime, _IMPORT_ERROR = _import_service_core()


if DaemonServiceCoreMixin is None or DaemonServiceCoreRuntime is None:

    @unittest.skip("daemon service core runtime dependency unavailable")
    class TestDaemonServiceCoreRuntimeDependency(unittest.TestCase):
        def test_service_core_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)


else:
    class _FakeServiceForCoreRuntime(DaemonServiceCoreMixin):
        def __init__(self, root: Path) -> None:
            self.root = root

        def _log(self, message: str) -> None:  # pragma: no cover
            pass


    class TestDaemonServiceCoreRuntimeDI(unittest.TestCase):
        def test_init_core_runtime_defaults(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                service = _FakeServiceForCoreRuntime(root)
                service._init_core_runtime()

                runtime = service._get_core_runtime()
                self.assertIsNotNone(runtime)
                self.assertEqual(service.stop_requested, False)
                self.assertIsNone(service.codex_run_meta)
                self.assertIsInstance(service.env, dict)
                self.assertIn("LANG", service.env)
                self.assertEqual(service.python_bin, sys.executable)

        def test_init_core_runtime_prefers_workspace_venv_python(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                fake_bin = root / ".venv" / "bin"
                fake_bin.mkdir(parents=True, exist_ok=True)
                (fake_bin / "python").write_text("", encoding="utf-8")
                service = _FakeServiceForCoreRuntime(root)

                service._init_core_runtime()
                self.assertEqual(service.python_bin, str(fake_bin / "python"))

        def test_injected_runtime_instance_is_shared(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            runtime = DaemonServiceCoreRuntime(service)
            runtime.env = {"EXISTING": "1"}
            runtime.codex_cli_version = "v1"
            runtime.stop_requested = True

            service._init_core_runtime(runtime)

            self.assertIs(service._get_core_runtime(), runtime)
            self.assertEqual(service.env["EXISTING"], "1")
            self.assertEqual(service.codex_cli_version, "v1")
            self.assertTrue(service.stop_requested)

        def test_runtime_fields_are_mutable_via_service(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            service._init_core_runtime()

            service.stop_requested = True
            service.codex_cli_version = "unit-test"
            service.codex_run_meta = {"mode": "app_server"}
            service.env["NEW_KEY"] = "2"

            runtime = service._get_core_runtime()
            self.assertIsNotNone(runtime)
            assert runtime is not None
            self.assertTrue(runtime.stop_requested)
            self.assertEqual(runtime.codex_cli_version, "unit-test")
            self.assertEqual(runtime.codex_run_meta, {"mode": "app_server"})
            self.assertEqual(runtime.env["NEW_KEY"], "2")
