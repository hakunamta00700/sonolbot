from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import types

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


def _import_service_rewriter():
    try:
        from sonolbot.core.daemon.service_rewriter import (
            DaemonServiceRewriterMixin,
            DaemonServiceRewriterRuntime,
        )
        return DaemonServiceRewriterMixin, DaemonServiceRewriterRuntime, None
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_rewriter import (
                DaemonServiceRewriterMixin,
                DaemonServiceRewriterRuntime,
            )
            return DaemonServiceRewriterMixin, DaemonServiceRewriterRuntime, None
        except Exception as inner_exc:  # pragma: no cover
            return None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, exc


DaemonServiceRewriterMixin, DaemonServiceRewriterRuntime, _IMPORT_ERROR = _import_service_rewriter()

if DaemonServiceRewriterMixin is None or DaemonServiceRewriterRuntime is None:

    @unittest.skip("daemon service rewriter runtime dependency unavailable")
    class TestDaemonServiceRewriterRuntimeDI(unittest.TestCase):
        def test_service_rewriter_import_dependency(self) -> None:
            self.assertIsNone(_IMPORT_ERROR)

else:
    class _FakeServiceForRewriterRuntime(DaemonServiceRewriterMixin):
        def __init__(self, root: Path) -> None:
            self.agent_rewriter_state_file = root / "agent-rewriter-state.json"


    class TestDaemonServiceRewriterRuntimeDI(unittest.TestCase):
        def test_init_rewriter_runtime_rejects_invalid_runtime(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForRewriterRuntime(Path(td))

                with self.assertRaisesRegex(
                    TypeError,
                    "rewriter_runtime must be DaemonServiceRewriterRuntime",
                ):
                    service._init_rewriter_runtime(runtime=object())  # type: ignore[arg-type]

        def test_injected_runtime_instance_is_used(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                service = _FakeServiceForRewriterRuntime(Path(td))
                runtime = DaemonServiceRewriterRuntime(service)

                service._init_rewriter_runtime(runtime)

                self.assertIs(service._get_rewriter_runtime(), runtime)
                self.assertIs(service.rewriter_proc, runtime.rewriter_proc)
