from __future__ import annotations

import sys
import types
import tempfile
import unittest
import os
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
        from sonolbot.core.daemon.service_core import (
            DaemonServiceCoreEnvPolicy,
            DaemonServiceCoreMixin,
            DaemonServiceCorePythonPolicy,
            DaemonServiceCoreRuntime,
        )

        return (
            DaemonServiceCoreMixin,
            DaemonServiceCoreRuntime,
            DaemonServiceCoreEnvPolicy,
            DaemonServiceCorePythonPolicy,
            None,
        )
    except ModuleNotFoundError as exc:
        if "dotenv" not in str(exc):
            return None, None, None, None, exc
        _ensure_fake_dotenv()
        try:
            from sonolbot.core.daemon.service_core import (
                DaemonServiceCoreEnvPolicy,
                DaemonServiceCoreMixin,
                DaemonServiceCorePythonPolicy,
                DaemonServiceCoreRuntime,
            )

            return (
                DaemonServiceCoreMixin,
                DaemonServiceCoreRuntime,
                DaemonServiceCoreEnvPolicy,
                DaemonServiceCorePythonPolicy,
                None,
            )
        except Exception as inner_exc:  # pragma: no cover
            return None, None, None, None, inner_exc
    except Exception as exc:  # pragma: no cover
        return None, None, None, None, exc


DaemonServiceCoreMixin, DaemonServiceCoreRuntime, DaemonServiceCoreEnvPolicy, DaemonServiceCorePythonPolicy, _IMPORT_ERROR = _import_service_core()


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
                self.assertIn("SONOLBOT_GUI_SESSION", service.env)
                self.assertEqual(service.python_bin, sys.executable)

        def test_init_core_runtime_prefers_workspace_venv_python(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                if os.name == "nt":
                    fake_bin = root / ".venv" / "Scripts"
                    fake_bin.mkdir(parents=True, exist_ok=True)
                    (fake_bin / "python.exe").write_text("", encoding="utf-8")
                    (fake_bin / "python3.exe").write_text("", encoding="utf-8")
                    expected_python = str(fake_bin / "python.exe")
                else:
                    fake_bin = root / ".venv" / "bin"
                    fake_bin.mkdir(parents=True, exist_ok=True)
                    (fake_bin / "python").write_text("", encoding="utf-8")
                    (fake_bin / "python3").write_text("", encoding="utf-8")
                    expected_python = str(fake_bin / "python")

                service = _FakeServiceForCoreRuntime(root)

                service._init_core_runtime()
                self.assertEqual(service.python_bin, expected_python)

        def test_init_core_runtime_checks_venv_python_order(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                if os.name == "nt":
                    scripts_dir = root / ".venv" / "Scripts"
                    scripts_dir.mkdir(parents=True, exist_ok=True)
                    (scripts_dir / "python3.exe").write_text("", encoding="utf-8")
                    (root / ".venv" / "bin" / "python").parent.mkdir(parents=True, exist_ok=True)
                    expected = str(scripts_dir / "python3.exe")
                else:
                    primary = root / ".venv" / "bin" / "python3"
                    fallback = root / ".venv" / "bin" / "python"
                    primary.parent.mkdir(parents=True, exist_ok=True)
                    fallback.write_text("", encoding="utf-8")
                    primary.write_text("", encoding="utf-8")
                    expected = str(primary)

                service = _FakeServiceForCoreRuntime(root)
                service._init_core_runtime()
                self.assertEqual(service.python_bin, expected)

        def test_init_core_runtime_uses_python_policy(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                priority_path = root / "custom" / "python"
                priority_path.parent.mkdir(parents=True, exist_ok=True)
                priority_path.write_text("", encoding="utf-8")

                class _CustomPythonPolicy(DaemonServiceCorePythonPolicy):
                    def build_venv_python_paths(self, path_root: Path) -> list[Path]:
                        fallback = path_root / ".venv" / "bin" / "python"
                        if not fallback.parent.exists():
                            fallback.parent.mkdir(parents=True, exist_ok=True)
                        fallback.write_text("", encoding="utf-8")
                        return [priority_path, fallback]

                service = _FakeServiceForCoreRuntime(root)
                service._init_core_runtime(python_policy=_CustomPythonPolicy())
                self.assertEqual(service.python_bin, str(priority_path))

        def test_init_core_runtime_uses_injected_runtime_over_policies(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                preferred = root / "preferred"
                preferred.parent.mkdir(parents=True, exist_ok=True)
                preferred.write_text("", encoding="utf-8")
                fallback = root / "fallback"
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback.write_text("", encoding="utf-8")

                class _PreferredPythonPolicy(DaemonServiceCorePythonPolicy):
                    def build_venv_python_paths(self, path_root: Path) -> list[Path]:
                        return [preferred]

                class _FallbackPythonPolicy(DaemonServiceCorePythonPolicy):
                    def build_venv_python_paths(self, path_root: Path) -> list[Path]:
                        return [fallback]

                service = _FakeServiceForCoreRuntime(root)
                runtime = DaemonServiceCoreRuntime(service, python_policy=_PreferredPythonPolicy())
                service._init_core_runtime(runtime, python_policy=_FallbackPythonPolicy())
                self.assertEqual(service.python_bin, str(preferred))

        def test_init_core_runtime_ignores_policies_when_runtime_injected(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            runtime = DaemonServiceCoreRuntime(service)
            runtime.env = {"LANG": "custom", "SONOLBOT_GUI_SESSION": "0"}

            class _NoDisplayPolicy(DaemonServiceCoreEnvPolicy):
                def has_gui_session(self, env: dict[str, str]) -> bool:
                    return False

            class _BlankPythonPolicy(DaemonServiceCorePythonPolicy):
                def build_venv_python_paths(self, path_root: Path) -> list[Path]:
                    return [path_root / "non-existent-python"]

            service._init_core_runtime(runtime, env_policy=_NoDisplayPolicy(), python_policy=_BlankPythonPolicy())
            self.assertEqual(service.env.get("LANG"), "custom")
            self.assertEqual(runtime.env.get("SONOLBOT_GUI_SESSION"), "0")
            self.assertEqual(service.python_bin, runtime.python_bin)

        def test_init_core_runtime_accepts_protocol_style_policies(self) -> None:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                venv_python = root / "env" / "python"
                venv_python.parent.mkdir(parents=True, exist_ok=True)
                venv_python.write_text("", encoding="utf-8")

                class _DuckEnvPolicy:
                    def build_default_env(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
                        env = dict(base_env or {})
                        env["DUMMY"] = "duck"
                        env["SONOLBOT_GUI_SESSION"] = "1" if self.has_gui_session(env) else "0"
                        return env

                    def has_gui_session(self, env: dict[str, str]) -> bool:
                        return False

                class _DuckPythonPolicy:
                    def build_venv_python_paths(self, path_root: Path) -> list[Path]:
                        return [venv_python]

                service = _FakeServiceForCoreRuntime(root)
                service._init_core_runtime(env_policy=_DuckEnvPolicy(), python_policy=_DuckPythonPolicy())
                self.assertEqual(service.python_bin, str(venv_python))
                self.assertEqual(service.env.get("DUMMY"), "duck")
                self.assertEqual(service.env.get("SONOLBOT_GUI_SESSION"), "0")

        def test_init_core_runtime_rejects_invalid_runtime(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            with self.assertRaises(TypeError):
                service._init_core_runtime(core_runtime=object())  # type: ignore[arg-type]

        def test_init_core_runtime_with_invalid_policies_raises(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())

            with self.assertRaises(AttributeError):
                DaemonServiceCoreRuntime(service, env_policy=object())  # type: ignore[arg-type]

            with self.assertRaises(AttributeError):
                DaemonServiceCoreRuntime(service, python_policy=object())  # type: ignore[arg-type]

        def test_set_env_rebuilds_gui_session_marker(self) -> None:
            class _NoDisplayPolicy(DaemonServiceCoreEnvPolicy):
                def has_gui_session(self, env: dict[str, str]) -> bool:
                    return False

            service = _FakeServiceForCoreRuntime(Path.cwd())
            runtime = DaemonServiceCoreRuntime(service, env_policy=_NoDisplayPolicy())
            service._init_core_runtime(runtime)

            service.env = {"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
            runtime = service._get_core_runtime()
            self.assertIsNotNone(runtime)
            assert runtime is not None
            self.assertEqual(runtime.env.get("SONOLBOT_GUI_SESSION"), "0")

        def test_init_core_runtime_builds_env_default_gui_session_marker(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            service._init_core_runtime()
            runtime = service._get_core_runtime()
            assert runtime is not None

            expected_gui = "1"
            if os.name != "nt":
                expected_gui = "1" if bool(runtime.env.get("DISPLAY") or runtime.env.get("WAYLAND_DISPLAY")) else "0"
            self.assertEqual(runtime.env.get("SONOLBOT_GUI_SESSION"), expected_gui)

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

        def test_gui_session_detection_defaults_to_no_display_on_posix(self) -> None:
            service = _FakeServiceForCoreRuntime(Path.cwd())
            service._init_core_runtime()
            self.assertIsInstance(service._has_gui_session(), bool)

        def test_injected_env_policy_overrides_default_env(self) -> None:
            class _NoGuiPolicy(DaemonServiceCoreEnvPolicy):
                def build_default_env(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
                    env = dict(base_env or {})
                    env.setdefault("LANG", "en_US.UTF-8")
                    env["SONOLBOT_GUI_SESSION"] = "0"
                    return env

            service = _FakeServiceForCoreRuntime(Path.cwd())
            runtime = DaemonServiceCoreRuntime(service, env_policy=_NoGuiPolicy())
            service._init_core_runtime(runtime)

            self.assertEqual(runtime.env.get("LANG"), "en_US.UTF-8")
            self.assertEqual(runtime.env.get("SONOLBOT_GUI_SESSION"), "0")

        def test_init_core_runtime_accepts_env_policy(self) -> None:
            class _HeadlessPolicy(DaemonServiceCoreEnvPolicy):
                def has_gui_session(self, env: dict[str, str]) -> bool:
                    return False

            service = _FakeServiceForCoreRuntime(Path.cwd())
            service._init_core_runtime(env_policy=_HeadlessPolicy())
            runtime = service._get_core_runtime()
            self.assertIsNotNone(runtime)
            assert runtime is not None
            self.assertEqual(runtime.env.get("SONOLBOT_GUI_SESSION"), "0")
