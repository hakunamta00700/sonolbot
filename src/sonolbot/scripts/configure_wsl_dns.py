"""WSL .wslconfig updater converted from PowerShell helper."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _find_section(lines: list[str], section: str) -> tuple[int, int]:
    start = -1
    for idx, line in enumerate(lines):
        if line.strip().lower() == f"[{section.lower()}]":
            start = idx
            break
    if start < 0:
        return -1, -1

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip().startswith("[") and lines[idx].strip().endswith("]"):
            end = idx
            break
    return start, end


def configure_wsl_dns(networking_mode: str = "") -> dict[str, str | bool]:
    """Update ~/.wslconfig and return change metadata."""

    root = Path.home()
    path = root / ".wslconfig"
    lines = _read_lines(path)
    start, end = _find_section(lines, "wsl2")
    changed = False

    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[wsl2]")
        start = len(lines) - 1
        end = len(lines)
        changed = True

    section = lines[start + 1 : end]
    section_lines = []
    keys: dict[str, int] = {}
    for idx, raw in enumerate(section):
        key = raw.split("=", 1)[0].strip().lower() if "=" in raw else ""
        if key and not raw.strip().startswith("#"):
            keys[key] = idx
        section_lines.append(raw)

    def upsert(key: str, value: str) -> None:
        nonlocal section_lines, keys, changed
        target = f"{key}={value}"
        target_key = key.lower()
        if target_key in keys:
            idx = keys[target_key]
            if section_lines[idx].strip() != target:
                section_lines[idx] = target
                changed = True
            return
        section_lines.append(target)
        keys[target_key] = len(section_lines) - 1
        changed = True

    if networking_mode:
        upsert("networkingMode", networking_mode)
        upsert("localhostForwarding", "true")

    new_lines = lines[: start + 1] + section_lines + lines[end:]
    if changed:
        if path.exists():
            backup = path.with_name(f"{path.name}.bak")
            idx = 1
            while backup.exists():
                backup = path.with_name(f"{path.name}.bak-{idx}")
                idx += 1
            path.rename(backup)
        _write_lines(path, new_lines)

    return {
        "wslconfig_path": str(path),
        "changed": changed,
    }
