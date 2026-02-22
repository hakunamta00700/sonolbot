"""Click-based command line interface for Sonolbot."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import click

from sonolbot.runtime import agent_home, codex_root, project_root, skills_root
from sonolbot.scripts import control_panel as control_panel_script
from sonolbot.scripts.setup_admin import run_setup_admin
from sonolbot.scripts.setup_wsl import run_setup_wsl
from sonolbot.scripts import configure_wsl_dns


def _project() -> Path:
    return project_root()


def _to_env_path(path: str) -> Path:
    return Path(path).expanduser()


def _run_python_module(module: str, args: Iterable[str] | None = None, *, check: bool = True) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_project()) + (os.pathsep + env.get("PYTHONPATH", ""))
    proc = subprocess.run([sys.executable, "-m", module, *list(args or [])], cwd=str(_project()), env=env)
    if check and proc.returncode != 0:
        raise click.ClickException(f"command failed: {module} (exit={proc.returncode})")
    return proc.returncode


def _run_script(path: str, args: Iterable[str] | None = None, *, check: bool = True) -> int:
    target = _project() / path
    if not target.exists():
        raise click.ClickException(f"missing script: {target}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_project()) + (os.pathsep + env.get("PYTHONPATH", ""))
    proc = subprocess.run([sys.executable, str(target), *list(args or [])], cwd=str(_project()), env=env)
    if check and proc.returncode != 0:
        raise click.ClickException(f"command failed: {target} (exit={proc.returncode})")
    return proc.returncode


def _resolve_agent_codex_root() -> Path:
    configured = os.environ.get("SONOLBOT_AGENT_HOME", "").strip()
    if configured:
        return _to_env_path(configured) / ".codex"
    return codex_root()


def _list_py_modules(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted([p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and not p.name.startswith("__")])


@click.group()
@click.option("--agent-home", default=None, help="Coding-agent runtime path (AGENTS / .codex).")
@click.pass_context
def main(ctx: click.Context, agent_home: str | None) -> None:
    if agent_home:
        os.environ["SONOLBOT_AGENT_HOME"] = os.path.abspath(agent_home)
    ctx.obj = {"agent_home": os.environ.get("SONOLBOT_AGENT_HOME", "")}


@main.command("version", help="Print sonolbot version.")
def cmd_version() -> None:
    from sonolbot import __version__

    click.echo(__version__)


@main.command("check", help="Run quick pending message check.")
def cmd_check() -> None:
    _run_python_module("sonolbot.core.quick_check", check=False)


@main.command("get-my-id", help="Show Telegram ID of current bot token.")
def cmd_get_my_id() -> None:
    _run_python_module("sonolbot.core.get_my_id")


@main.command("autoexecutor", help="Run daemon service in foreground (legacy mybot_autoexecutor).")
def cmd_autoexecutor() -> None:
    from sonolbot.scripts.mybot_autoexecutor import run_daemon_service

    raise SystemExit(run_daemon_service())


@main.group(help="Daemon commands.")
def daemon() -> None:
    pass


@daemon.command("start", help="Start daemon_service.py.")
@click.argument("args", nargs=-1)
def daemon_start(args: tuple[str, ...]) -> None:
    _run_python_module("sonolbot.core.daemon_service", args)


@daemon.command("drain", help="Process pending updates once.")
@click.option("--max-cycles", default=120, type=int)
@click.option("--sleep-sec", default=1.0, type=float)
@click.option("--no-lock", is_flag=True, default=False, help="Do not acquire queue lock.")
def daemon_drain(max_cycles: int, sleep_sec: float, no_lock: bool) -> None:
    args = ["--max-cycles", str(max_cycles), "--sleep-sec", str(sleep_sec)]
    if no_lock:
        args.append("--no-lock")
    _run_python_module("sonolbot.core.process_pending", args)


@main.group(help="Panel commands.")
def panel() -> None:
    pass


@panel.command("start", help="Start control panel UI.")
@click.argument("args", nargs=-1)
def panel_start(args: tuple[str, ...]) -> None:
    _run_python_module("sonolbot.core.daemon_control_panel", args)


@panel.command("build-exe", help="Build control_panel.exe with PyInstaller.")
def panel_build_exe() -> None:
    raise SystemExit(control_panel_script.build_control_panel_exe())


@main.group(help="Task list/activation commands.")
def task() -> None:
    pass


@task.command("list", help="List tasks.")
@click.option("--tasks-dir", default=str(_project() / "tasks"), show_default=True)
@click.option("--limit", default=50, type=int, show_default=True)
@click.option("--keyword", default="")
@click.option("--json", "json_output", is_flag=True, default=False)
def task_list(tasks_dir: str, limit: int, keyword: str, json_output: bool) -> None:
    args = ["list", "--tasks-dir", tasks_dir, "--limit", str(limit), "--keyword", keyword]
    if json_output:
        args.append("--json")
    _run_script("scripts/task_commands.py", args)


@task.command("activate", help="Resolve one task by id/keyword.")
@click.argument("target")
@click.option("--tasks-dir", default=str(_project() / "tasks"), show_default=True)
@click.option("--include-instrunction", is_flag=True, default=False)
@click.option("--json", "json_output", is_flag=True, default=False)
def task_activate(target: str, tasks_dir: str, include_instrunction: bool, json_output: bool) -> None:
    args = ["activate", target, "--tasks-dir", tasks_dir]
    if include_instrunction:
        args.append("--include-instrunction")
    if json_output:
        args.append("--json")
    _run_script("scripts/task_commands.py", args)


@main.group(help="Skill helper commands (.codex/skills).")
def skill() -> None:
    pass


@skill.command("list", help="List available skills.")
@click.option("--json", is_flag=True, default=False)
def skill_list(json_output: bool) -> None:
    root = skills_root()
    if not root.exists():
        raise click.ClickException(f"skills root not found: {root}")

    items = []
    for path in sorted(p for p in root.iterdir() if p.is_dir() and p.name):
        name = path.name
        summary = ""
        skill_md = path / "SKILL.md"
        if skill_md.exists():
            for line in skill_md.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip():
                    summary = line.strip()
                    break
        items.append({"name": name, "path": str(path), "summary": summary})
        if not json_output:
            click.echo(f"- {name}: {path}")
            if summary:
                click.echo(f"  {summary}")

    if json_output:
        click.echo(json.dumps(items, ensure_ascii=False, indent=2))


@skill.command("install", help="Install skill directory to runtime .codex/skills.")
@click.argument("source")
@click.option("--name", default="", help="Target skill name (defaults to source directory name).")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing skill.")
def skill_install(source: str, name: str, force: bool) -> None:
    src = _to_env_path(source).resolve()
    if not src.exists() or not src.is_dir():
        raise click.ClickException(f"invalid source: {source}")
    if not (src / "SKILL.md").exists():
        raise click.ClickException("source path must contain SKILL.md")

    dst = _resolve_agent_codex_root() / "skills" / (name or src.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if not force:
            raise click.ClickException(f"skill exists: {dst} (use --force)")
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    click.echo(f"installed: {src} -> {dst}")


@main.group(help="Setup helpers.")
def setup() -> None:
    pass


@setup.command("wsl", help="Run setup_wsl equivalent.")
@click.option("--auto-apt-install", is_flag=True, default=False, help="Try apt-get install when dependency is missing.")
@click.option("--skip-env", is_flag=True, default=False, help="Skip .env creation/update.")
def setup_wsl(auto_apt_install: bool, skip_env: bool) -> None:
    raise SystemExit(
        run_setup_wsl(
            auto_apt_install=auto_apt_install,
            skip_env=skip_env,
        )
    )


@setup.command("admin", help="Run setup + optionally launch control panel.")
@click.option("--panel", is_flag=True, default=False)
def setup_admin(panel: bool) -> None:
    raise SystemExit(
        run_setup_admin(
            run_panel=panel,
            default_panel=False,
        )
    )


@setup.command("configure-wsl-dns", help="Write WSL2 networkingMode into ~/.wslconfig.")
@click.option(
    "--networking-mode",
    type=click.Choice(["", "nat", "mirrored", "virtioproxy"]),
    default="",
    show_default=True,
)
def setup_configure_wsl_dns(networking_mode: str) -> None:
    result = configure_wsl_dns.configure_wsl_dns(networking_mode)
    click.echo(f"WSLCONFIG_PATH={result['wslconfig_path']}")
    click.echo(f"CHANGED={1 if result['changed'] else 0}")
    if networking_mode:
        click.echo(f"NETWORKING_MODE={networking_mode}")


if __name__ == "__main__":
    main()
