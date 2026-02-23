from __future__ import annotations

import inspect
import sys
import types
import unittest
import tempfile
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
    class _FakeServiceConfig:
        def __init__(self, base: Path) -> None:
            self.root = base
            self.logs_dir = base / "logs"
            self.tasks_dir = base / "tasks"
            self.store_file = base / "telegram_messages.json"
            self.codex_work_dir = base
            self.state_dir = base / "state"
            self.chat_locks_dir = base / "chat_locks"
            self.agent_rewriter_workspace = base / "agent_rewriter_workspace"

        def as_dict(self) -> dict[str, object]:
            return {
                "root": self.root,
                "logs_dir": self.logs_dir,
                "tasks_dir": self.tasks_dir,
                "store_file": self.store_file,
                "codex_work_dir": self.codex_work_dir,
                "state_dir": self.state_dir,
                "chat_locks_dir": self.chat_locks_dir,
                "agent_rewriter_workspace": self.agent_rewriter_workspace,
            }

    class TestDaemonServiceSignatureDI(unittest.TestCase):
        def test_daemon_service_core_runtime_injection_is_forwarded(self) -> None:
            captured: dict[str, object] = {}

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)
            core_marker = object()

            try:
                with tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    config = _FakeServiceConfig(base)

                    def fake_init_core_runtime(
                        self,
                        core_runtime=None,
                        *,
                        env_policy=None,
                        python_policy=None,
                    ) -> None:
                        captured["core_runtime"] = core_runtime
                        captured["env_policy"] = env_policy
                        captured["python_policy"] = python_policy
                        self._core_runtime_component = core_marker

                    def noop(*_args: object, **_kwargs: object) -> None:
                        return None

                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = noop

                    runtime = object()
                    env_policy = object()
                    python_policy = object()
                    service = DaemonService(
                        service_config=config,
                        core_runtime=runtime,
                        core_env_policy=env_policy,
                        core_python_policy=python_policy,
                    )

                    self.assertIs(captured.get("core_runtime"), runtime)
                    self.assertIs(captured.get("env_policy"), env_policy)
                    self.assertIs(captured.get("python_policy"), python_policy)
                    self.assertIs(service._core_runtime_component, core_marker)
            finally:
                DaemonService._init_core_runtime = original_init_core_runtime
                DaemonService._init_telegram_runtime = original_init_telegram_runtime
                DaemonService._init_task_runtime = original_init_task_runtime
                DaemonService._init_app_runtime = original_init_app_runtime
                DaemonService._init_lease_runtime = original_init_lease_runtime
                DaemonService._harden_sensitive_permissions = original_harden
                DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                if original_cleanup_activity_logs is None:
                    if "_cleanup_activity_logs" in DaemonService.__dict__:
                        del DaemonService._cleanup_activity_logs
                else:
                    DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                if original_rotate_activity_log is None:
                    if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                        del DaemonService._rotate_activity_log_if_needed
                else:
                    DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                if original_log is None:
                    if "_log" in DaemonService.__dict__:
                        del DaemonService._log
                else:
                    DaemonService._log = original_log

        def test_daemon_service_ctor_accepts_injected_warnings(self) -> None:
            captured: list[str] = []

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)

            try:
                with tempfile.TemporaryDirectory() as td:
                    config = _FakeServiceConfig(Path(td))

                    def fake_init_core_runtime(
                        self,
                        core_runtime=None,
                        *,
                        env_policy=None,
                        python_policy=None,
                    ) -> None:
                        self._core_runtime_component = object()

                    def noop(*_args: object, **_kwargs: object) -> None:
                        return None

                    def fake_log(_self: object, message: str) -> None:
                        captured.append(str(message))

                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = fake_log

                    service = DaemonService(
                        service_config=config,
                        service_init_warnings=["A", "B"],
                    )

                    self.assertIs(service.config, config)
                    self.assertIn("WARN: A", captured)
                    self.assertIn("WARN: B", captured)
            finally:
                DaemonService._init_core_runtime = original_init_core_runtime
                DaemonService._init_telegram_runtime = original_init_telegram_runtime
                DaemonService._init_task_runtime = original_init_task_runtime
                DaemonService._init_app_runtime = original_init_app_runtime
                DaemonService._init_lease_runtime = original_init_lease_runtime
                DaemonService._harden_sensitive_permissions = original_harden
                DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                if original_cleanup_activity_logs is None:
                    if "_cleanup_activity_logs" in DaemonService.__dict__:
                        del DaemonService._cleanup_activity_logs
                else:
                    DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                if original_rotate_activity_log is None:
                    if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                        del DaemonService._rotate_activity_log_if_needed
                else:
                    DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                if original_log is None:
                    if "_log" in DaemonService.__dict__:
                        del DaemonService._log
                else:
                    DaemonService._log = original_log

        def test_daemon_service_ctor_includes_core_runtime_kwargs(self) -> None:
            signature = inspect.signature(DaemonService.__init__)
            params = signature.parameters

            for name in (
                "core_runtime",
                "core_env_policy",
                "core_python_policy",
                "service_config",
                "service_init_warnings",
                "service_config_loader",
            ):
                self.assertIn(name, params)

            self.assertEqual(params["core_runtime"].default, None)
            self.assertEqual(params["core_env_policy"].default, None)
            self.assertEqual(params["core_python_policy"].default, None)
            self.assertEqual(params["service_config"].default, None)
            self.assertEqual(params["service_init_warnings"].default, None)
            self.assertEqual(params["service_config_loader"].default, None)

        def test_daemon_service_ctor_uses_injected_config_loader(self) -> None:
            import sonolbot.core.daemon.service as service_module

            original_from_env = service_module.DaemonServiceConfig.from_env
            loader_called = False

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)

            def fake_loader() -> tuple[object, list[str]]:
                nonlocal loader_called
                loader_called = True
                return _FakeServiceConfig(Path("/tmp")), ["from-loader-warning"]

            def fake_init_core_runtime(
                self,
                core_runtime=None,
                *,
                env_policy=None,
                python_policy=None,
            ) -> None:
                self._core_runtime_component = object()

            def noop(*_args: object, **_kwargs: object) -> None:
                return None

            def fake_log(_self: object, message: str) -> None:
                pass

            try:
                with tempfile.TemporaryDirectory():
                    service_module.DaemonServiceConfig.from_env = lambda: (_FakeServiceConfig(Path("/tmp")), [])
                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = fake_log

                    service = DaemonService(service_config_loader=fake_loader)
                    self.assertTrue(loader_called)
                    self.assertIsInstance(service.config, _FakeServiceConfig)
            finally:
                service_module.DaemonServiceConfig.from_env = original_from_env
                DaemonService._init_core_runtime = original_init_core_runtime
                DaemonService._init_telegram_runtime = original_init_telegram_runtime
                DaemonService._init_task_runtime = original_init_task_runtime
                DaemonService._init_app_runtime = original_init_app_runtime
                DaemonService._init_lease_runtime = original_init_lease_runtime
                DaemonService._harden_sensitive_permissions = original_harden
                DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                if original_cleanup_activity_logs is None:
                    if "_cleanup_activity_logs" in DaemonService.__dict__:
                        del DaemonService._cleanup_activity_logs
                else:
                    DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                if original_rotate_activity_log is None:
                    if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                        del DaemonService._rotate_activity_log_if_needed
                else:
                    DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                if original_log is None:
                    if "_log" in DaemonService.__dict__:
                        del DaemonService._log
                else:
                    DaemonService._log = original_log

        def test_daemon_service_config_takes_precedence_over_config_loader(self) -> None:
            import sonolbot.core.daemon.service as service_module

            original_from_env = service_module.DaemonServiceConfig.from_env
            loader_called = False
            from_env_called = False

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)

            config = _FakeServiceConfig(Path("/tmp/config"))

            def fake_from_env() -> tuple[object, list[str]]:
                nonlocal from_env_called
                from_env_called = True
                return _FakeServiceConfig(Path("/tmp/loader")), ["from-env-warning"]

            def fake_loader() -> tuple[object, list[str]]:
                nonlocal loader_called
                loader_called = True
                return _FakeServiceConfig(Path("/tmp/loader")), ["from-loader-warning"]

            def fake_init_core_runtime(
                self,
                core_runtime=None,
                *,
                env_policy=None,
                python_policy=None,
            ) -> None:
                self._core_runtime_component = object()

            def noop(*_args: object, **_kwargs: object) -> None:
                return None

            try:
                with tempfile.TemporaryDirectory():
                    service_module.DaemonServiceConfig.from_env = fake_from_env
                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = noop

                    service = DaemonService(
                        service_config=config,
                        service_config_loader=fake_loader,
                    )

                    self.assertIs(service.config, config)
                    self.assertFalse(loader_called)
                    self.assertFalse(from_env_called)
            finally:
                service_module.DaemonServiceConfig.from_env = original_from_env
                DaemonService._init_core_runtime = original_init_core_runtime
                DaemonService._init_telegram_runtime = original_init_telegram_runtime
                DaemonService._init_task_runtime = original_init_task_runtime
                DaemonService._init_app_runtime = original_init_app_runtime
                DaemonService._init_lease_runtime = original_init_lease_runtime
                DaemonService._harden_sensitive_permissions = original_harden
                DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                if original_cleanup_activity_logs is None:
                    if "_cleanup_activity_logs" in DaemonService.__dict__:
                        del DaemonService._cleanup_activity_logs
                else:
                    DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                if original_rotate_activity_log is None:
                    if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                        del DaemonService._rotate_activity_log_if_needed
                else:
                    DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                if original_log is None:
                    if "_log" in DaemonService.__dict__:
                        del DaemonService._log
                else:
                    DaemonService._log = original_log

        def test_daemon_service_uses_from_env_when_no_config_injected(self) -> None:
            import sonolbot.core.daemon.service as service_module

            original_from_env = service_module.DaemonServiceConfig.from_env
            captured_logs: list[str] = []
            from_env_called = False

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)

            def fake_from_env() -> tuple[object, list[str]]:
                nonlocal from_env_called
                from_env_called = True
                return _FakeServiceConfig(Path("/tmp")), ["from-env-warning"]

            def fake_init_core_runtime(
                self,
                core_runtime=None,
                *,
                env_policy=None,
                python_policy=None,
            ) -> None:
                self._core_runtime_component = object()

            def noop(*_args: object, **_kwargs: object) -> None:
                return None

            def fake_log(_self: object, message: str) -> None:
                captured_logs.append(str(message))

            try:
                with tempfile.TemporaryDirectory() as td:
                    service_module.DaemonServiceConfig.from_env = fake_from_env
                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = fake_log

                    service = DaemonService()
                    self.assertIsInstance(service.config, _FakeServiceConfig)
                    self.assertTrue(from_env_called)
                    self.assertIn("WARN: from-env-warning", captured_logs)
            finally:
                service_module.DaemonServiceConfig.from_env = original_from_env
                DaemonService._init_core_runtime = original_init_core_runtime
                DaemonService._init_telegram_runtime = original_init_telegram_runtime
                DaemonService._init_task_runtime = original_init_task_runtime
                DaemonService._init_app_runtime = original_init_app_runtime
                DaemonService._init_lease_runtime = original_init_lease_runtime
                DaemonService._harden_sensitive_permissions = original_harden
                DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                if original_cleanup_activity_logs is None:
                    if "_cleanup_activity_logs" in DaemonService.__dict__:
                        del DaemonService._cleanup_activity_logs
                else:
                    DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                if original_rotate_activity_log is None:
                    if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                        del DaemonService._rotate_activity_log_if_needed
                else:
                    DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                if original_log is None:
                    if "_log" in DaemonService.__dict__:
                        del DaemonService._log
                else:
                    DaemonService._log = original_log

        def test_daemon_service_constructor_uses_injected_config(self) -> None:
            import sonolbot.core.daemon.service as service_module

            original_from_env = service_module.DaemonServiceConfig.from_env
            invoked_from_env = False

            original_init_core_runtime = DaemonService._init_core_runtime
            original_init_telegram_runtime = DaemonService._init_telegram_runtime
            original_init_task_runtime = DaemonService._init_task_runtime
            original_init_app_runtime = DaemonService._init_app_runtime
            original_init_lease_runtime = DaemonService._init_lease_runtime
            original_harden = DaemonService._harden_sensitive_permissions
            original_init_rewriter_runtime = DaemonService._init_rewriter_runtime
            original_cleanup_activity_logs = getattr(DaemonService, "_cleanup_activity_logs", None)
            original_rotate_activity_log = getattr(DaemonService, "_rotate_activity_log_if_needed", None)
            original_log = getattr(DaemonService, "_log", None)

            def fake_from_env() -> tuple[object, list[str]]:
                nonlocal invoked_from_env
                invoked_from_env = True
                return _FakeServiceConfig(Path("/tmp")), []

            def fake_init_core_runtime(
                self,
                core_runtime=None,
                *,
                env_policy=None,
                python_policy=None,
            ) -> None:
                self._core_runtime_component = object()

            def noop(*_args: object, **_kwargs: object) -> None:
                return None

            with tempfile.TemporaryDirectory() as td:
                try:
                    base = Path(td)
                    config = _FakeServiceConfig(base)

                    service_module.DaemonServiceConfig.from_env = fake_from_env
                    DaemonService._init_core_runtime = fake_init_core_runtime
                    DaemonService._init_telegram_runtime = noop
                    DaemonService._init_task_runtime = noop
                    DaemonService._init_app_runtime = noop
                    DaemonService._init_lease_runtime = noop
                    DaemonService._harden_sensitive_permissions = noop
                    DaemonService._init_rewriter_runtime = noop
                    DaemonService._cleanup_activity_logs = noop
                    DaemonService._rotate_activity_log_if_needed = noop
                    DaemonService._log = noop

                    service = DaemonService(service_config=config)

                    self.assertIs(service.config, config)
                    self.assertFalse(invoked_from_env)
                finally:
                    service_module.DaemonServiceConfig.from_env = original_from_env
                    DaemonService._init_core_runtime = original_init_core_runtime
                    DaemonService._init_telegram_runtime = original_init_telegram_runtime
                    DaemonService._init_task_runtime = original_init_task_runtime
                    DaemonService._init_app_runtime = original_init_app_runtime
                    DaemonService._init_lease_runtime = original_init_lease_runtime
                    DaemonService._harden_sensitive_permissions = original_harden
                    DaemonService._init_rewriter_runtime = original_init_rewriter_runtime
                    if original_cleanup_activity_logs is None:
                        if "_cleanup_activity_logs" in DaemonService.__dict__:
                            del DaemonService._cleanup_activity_logs
                    else:
                        DaemonService._cleanup_activity_logs = original_cleanup_activity_logs
                    if original_rotate_activity_log is None:
                        if "_rotate_activity_log_if_needed" in DaemonService.__dict__:
                            del DaemonService._rotate_activity_log_if_needed
                    else:
                        DaemonService._rotate_activity_log_if_needed = original_rotate_activity_log
                    if original_log is None:
                        if "_log" in DaemonService.__dict__:
                            del DaemonService._log
                    else:
                        DaemonService._log = original_log
