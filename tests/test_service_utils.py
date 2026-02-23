"""Unit tests for daemon service utility functions."""

from __future__ import annotations

import os
import unittest

from sonolbot.core.daemon import service_utils


class _EnvCase(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)


class TestServiceUtilsEnv(_EnvCase):
    def test_env_int(self) -> None:
        os.environ["DAEMON_NUM"] = "42"
        self.assertEqual(service_utils.env_int("DAEMON_NUM", 1, minimum=1), 42)
        os.environ["DAEMON_NUM"] = "0"
        self.assertEqual(service_utils.env_int("DAEMON_NUM", 5, minimum=1), 1)
        os.environ["DAEMON_NUM"] = "bad"
        self.assertEqual(service_utils.env_int("DAEMON_NUM", 7, minimum=0), 7)

    def test_env_float(self) -> None:
        os.environ["DAEMON_FLOAT"] = "3.14"
        self.assertEqual(service_utils.env_float("DAEMON_FLOAT", 0.0, minimum=0.0), 3.14)
        os.environ["DAEMON_FLOAT"] = "bad"
        self.assertEqual(service_utils.env_float("DAEMON_FLOAT", 1.5, minimum=0.0), 1.5)

    def test_env_bool(self) -> None:
        os.environ["DAEMON_BOOL"] = "yes"
        self.assertTrue(service_utils.env_bool("DAEMON_BOOL", False))
        os.environ["DAEMON_BOOL"] = "0"
        self.assertFalse(service_utils.env_bool("DAEMON_BOOL", True))
        os.environ["DAEMON_BOOL"] = "na"
        self.assertEqual(service_utils.env_bool("DAEMON_BOOL", True), True)


class TestServiceUtilsText(unittest.TestCase):
    def test_normalize_thread_id_token(self) -> None:
        self.assertEqual(service_utils.normalize_thread_id_token("  THREAD_ABC "), "")
        self.assertEqual(
            service_utils.normalize_thread_id_token("12345678-1234-1234-1234-123456789012"),
            "12345678-1234-1234-1234-123456789012",
        )

    def test_split_text_chunks(self) -> None:
        text = "a" * 1200
        chunks = service_utils.split_text_chunks(text, max_chars=300)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))
        self.assertGreaterEqual(len(chunks), 4)

    def test_candidate_rows(self) -> None:
        rows = service_utils.build_candidate_keyboard_rows(
            ["  A  ", "", "B", " C "],
            main_menu_rows=[["M1"], ["M2"]],
            per_row=2,
        )
        self.assertEqual(rows, [["A", "B"], ["C"], ["M1"], ["M2"]])


if __name__ == "__main__":
    unittest.main()
