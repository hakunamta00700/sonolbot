"""Unit tests for daemon manager utility helpers."""

from __future__ import annotations

import os
import time
import unittest

from pathlib import Path

from sonolbot.core.daemon import manager_utils


class TestManagerUtilsAllowedUsers(unittest.TestCase):
    def test_normalize_allowed_users(self) -> None:
        self.assertEqual(
            manager_utils.normalize_allowed_users(["1", "2", "bad", 3]),
            [1, 2, 3],
        )
        self.assertEqual(manager_utils.normalize_allowed_users(None), [])

    def test_active_bots(self) -> None:
        cfg = {
            "allowed_users_global": [100, 200],
            "bots": [
                {"bot_id": "b1", "token": "t1", "active": True, "bot_name": "n1"},
                {"bot_id": "b2", "token": "t2", "active": False, "bot_name": "n2"},
                {"bot_id": "", "token": "t3", "active": True},
            ],
        }
        active = manager_utils.active_bots(cfg, [100, 200])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["bot_id"], "b1")
        self.assertEqual(active[0]["allowed_users_global"], [100, 200])


class TestManagerUtilsRestart(unittest.TestCase):
    def test_update_restart_state_reset(self) -> None:
        state: dict[str, object] = {}
        fail_count, next_start, backoff_sec, updated = manager_utils.update_restart_state(
            state,
            exit_code=0,
            runtime_sec=120.0,
            stable_reset_sec=60.0,
            base_backoff_sec=5.0,
            max_backoff_sec=120.0,
            now_epoch=10.0,
        )
        self.assertEqual(fail_count, 0)
        self.assertEqual(next_start, 0.0)
        self.assertEqual(backoff_sec, 0.0)
        self.assertEqual(updated["last_exit_rc"], 0)

    def test_update_restart_state_backoff(self) -> None:
        state: dict[str, object] = {}
        fail_count, next_start, backoff_sec, updated = manager_utils.update_restart_state(
            state,
            exit_code=1,
            runtime_sec=1.0,
            stable_reset_sec=60.0,
            base_backoff_sec=5.0,
            max_backoff_sec=120.0,
            now_epoch=10.0,
        )
        self.assertEqual(fail_count, 1)
        self.assertEqual(next_start, 15.0)
        self.assertEqual(backoff_sec, 5.0)
        self.assertEqual(updated["fail_count"], 1)

    def test_can_start_worker_now(self) -> None:
        state: dict[str, object] = {
            "next_start_at": 20.0,
            "last_skip_log_at": 10.0,
        }
        can_start, remaining, should_log = manager_utils.can_start_worker_now(
            state,
            now_epoch=25.0,
            poll_interval_sec=5.0,
        )
        self.assertTrue(can_start)
        self.assertFalse(should_log)

        state = {"next_start_at": 100.0, "last_skip_log_at": 40.0}
        can_start, remaining, should_log = manager_utils.can_start_worker_now(
            state,
            now_epoch=50.0,
            poll_interval_sec=5.0,
        )
        self.assertFalse(can_start)
        self.assertTrue(should_log)
        self.assertAlmostEqual(remaining, 50.0)


class TestManagerUtilsWorkerEnv(unittest.TestCase):
    def test_build_worker_env(self) -> None:
        bot = {"bot_id": "b1", "token": "t1", "allowed_users_global": [1, 2]}
        workspace = Path("/tmp/some")
        cfg = Path("/tmp/cfg")
        base_env = {"KEEP": "1"}
        env = manager_utils.build_worker_env(
            bot=bot,
            workspace=workspace,
            config_path=cfg,
            base_env=base_env,
            rewriter_tmp_root=Path("/tmp/rewriters"),
        )
        self.assertEqual(env["DAEMON_BOT_WORKER"], "1")
        self.assertEqual(env["TELEGRAM_ALLOWED_USERS"], "1,2")
        self.assertEqual(env["WORK_DIR"], str(workspace))
        self.assertEqual(env["SONOLBOT_BOTS_CONFIG"], str(cfg))


if __name__ == "__main__":
    unittest.main()
