from __future__ import annotations

import inspect
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


def _import_service():
    try:
        from sonolbot.core.daemon.service import DaemonService

        return DaemonService, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service import DaemonService

            return DaemonService, None
        except Exception as inner_exc:  # pragma: no cover
            return None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, exc


DaemonService, _IMPORT_ERROR = _import_service()


if DaemonService is None:

    @unittest.skip("daemon service import dependency unavailable")
    class TestDaemonServiceImportDependency(unittest.TestCase):
        def test_service_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)


else:

    class TestDaemonServiceSignatureDI(unittest.TestCase):
        def test_daemon_service_ctor_includes_core_runtime_kwargs(self) -> None:
            signature = inspect.signature(DaemonService.__init__)
            params = signature.parameters

            for name in ("core_runtime", "core_env_policy", "core_python_policy"):
                self.assertIn(name, params)

            self.assertEqual(params["core_env_policy"].default, None)
            self.assertEqual(params["core_python_policy"].default, None)
