"""CLI wrapper for control_panel.py build command."""

from __future__ import annotations

from sonolbot.scripts.control_panel import build_control_panel_exe


def main() -> int:
    return build_control_panel_exe()


if __name__ == "__main__":
    raise SystemExit(main())
