#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT/.env"
VENV_DIR="$ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
APT_UPDATED=0
PREREQ_BLOCKED=0
SETUP_NONINTERACTIVE="${SONOLBOT_SETUP_NONINTERACTIVE:-0}"
SETUP_PROMPT_TIMEOUT_SEC="${SONOLBOT_SETUP_PROMPT_TIMEOUT_SEC:-15}"
SETUP_AUTO_APT_INSTALL="${SONOLBOT_SETUP_AUTO_APT_INSTALL:-0}"

UI_LANG_RAW="${SONOLBOT_UI_LANG:-ko}"
UI_LANG="${UI_LANG_RAW,,}"
if [[ "$UI_LANG" != "ko" ]]; then
  UI_LANG="en"
fi

is_ko() {
  [[ "$UI_LANG" == "ko" ]]
}

msg() {
  local ko="$1"
  local en="$2"
  if is_ko; then
    echo "$ko"
  else
    echo "$en"
  fi
}

msg_inline() {
  local ko="$1"
  local en="$2"
  if is_ko; then
    printf "%s" "$ko"
  else
    printf "%s" "$en"
  fi
}

is_interactive_prompt() {
  [[ "$SETUP_NONINTERACTIVE" != "1" && -t 0 ]]
}

prompt_yes_no() {
  local message_ko="$1"
  local message_en="$2"
  local default_answer="${3:-N}"
  local answer=""
  local default_upper="${default_answer^^}"
  local timeout_sec="${SETUP_PROMPT_TIMEOUT_SEC}"

  if ! is_interactive_prompt; then
    answer="$default_upper"
    msg \
      "      [자동] 비대화형 실행으로 기본값 '${answer}' 적용" \
      "      [Auto] Non-interactive mode, using default '${answer}'"
  else
    if [[ "$timeout_sec" =~ ^[0-9]+$ ]] && (( timeout_sec > 0 )); then
      local prompt
      prompt="$(msg_inline "$message_ko" "$message_en")"
      if ! read -r -t "$timeout_sec" -p "$prompt" answer; then
        answer=""
      fi
    else
      local prompt
      prompt="$(msg_inline "$message_ko" "$message_en")"
      read -r -p "$prompt" answer
    fi
  fi

  if [[ -z "${answer:-}" ]]; then
    answer="$default_upper"
    msg \
      "      [자동] 입력이 없어 기본값 '${answer}' 적용" \
      "      [Auto] No input received, using default '${answer}'"
  fi

  [[ "${answer^^}" == "Y" || "${answer^^}" == "YES" ]]
}

apt_install_packages() {
  if [[ "$SETUP_AUTO_APT_INSTALL" != "1" ]]; then
    return 1
  fi

  local pkgs=("$@")
  local installer=()
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    if ! sudo -n true >/dev/null 2>&1; then
      return 1
    fi
    installer=(sudo -n apt-get)
  else
    installer=(apt-get)
  fi

  if [[ "$APT_UPDATED" -eq 0 ]]; then
    if ! "${installer[@]}" update; then
      return 1
    fi
    APT_UPDATED=1
  fi

  "${installer[@]}" install -y "${pkgs[@]}"
}

ensure_command_with_apt() {
  local cmd="$1"
  local pkg="$2"
  local install_reason_ko="$3"
  local install_reason_en="$4"
  local manual_install="$5"

  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi

  msg \
    "      [안내] ${install_reason_ko}에 필요한 '${cmd}' 명령이 없습니다." \
    "      [Info] '${cmd}' is missing, required for ${install_reason_en}."

  if [[ "$SETUP_AUTO_APT_INSTALL" == "1" ]] && apt_install_packages "$pkg" && command -v "$cmd" >/dev/null 2>&1; then
    msg "      '${cmd}' 자동 설치 완료" "      '${cmd}' auto-install completed"
    return 0
  fi

  msg "      [오류] '${cmd}' 설치가 필요합니다." "      [Error] '${cmd}' installation is required."
  if [[ "$SETUP_AUTO_APT_INSTALL" != "1" ]]; then
    msg \
      "      [안내] setup에서는 sudo 권한 설치를 자동 수행하지 않습니다." \
      "      [Info] setup does not auto-run sudo-based installs."
  else
    msg \
      "      [안내] 자동 설치에 실패했습니다. (sudo 인증/권한 필요 가능)" \
      "      [Info] Auto-install failed. (sudo authentication/permission may be required)"
  fi
  msg "      수동 설치: $manual_install" "      Manual install: $manual_install"
  PREREQ_BLOCKED=1
  return 1
}

ensure_python_stack() {
  ensure_command_with_apt \
    "python3" \
    "python3" \
    "setup 실행" \
    "running setup" \
    "sudo apt-get update && sudo apt-get install -y python3" || true

  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi

  if ! python3 -m pip --version >/dev/null 2>&1; then
    msg \
      "      [안내] python3-pip가 없어 pip를 사용할 수 없습니다." \
      "      [Info] python3-pip is missing, so pip is unavailable."
    if [[ "$SETUP_AUTO_APT_INSTALL" == "1" ]] && apt_install_packages python3-pip && python3 -m pip --version >/dev/null 2>&1; then
      msg "      python3-pip 자동 설치 완료" "      python3-pip auto-install completed"
    else
      msg "      [오류] python3-pip 설치가 필요합니다." "      [Error] python3-pip installation is required."
      if [[ "$SETUP_AUTO_APT_INSTALL" != "1" ]]; then
        msg \
          "      [안내] setup에서는 sudo 권한 설치를 자동 수행하지 않습니다." \
          "      [Info] setup does not auto-run sudo-based installs."
      fi
      msg \
        "      수동 설치: sudo apt-get update && sudo apt-get install -y python3-pip" \
        "      Manual install: sudo apt-get update && sudo apt-get install -y python3-pip"
      PREREQ_BLOCKED=1
    fi
  fi

  if ! python3 -m venv -h >/dev/null 2>&1; then
    msg \
      "      [안내] python3-venv가 없어 가상환경을 만들 수 없습니다." \
      "      [Info] python3-venv is missing, so virtualenv cannot be created."
    if [[ "$SETUP_AUTO_APT_INSTALL" == "1" ]] && apt_install_packages python3-venv && python3 -m venv -h >/dev/null 2>&1; then
      msg "      python3-venv 자동 설치 완료" "      python3-venv auto-install completed"
    else
      msg "      [오류] python3-venv 설치가 필요합니다." "      [Error] python3-venv installation is required."
      if [[ "$SETUP_AUTO_APT_INSTALL" != "1" ]]; then
        msg \
          "      [안내] setup에서는 sudo 권한 설치를 자동 수행하지 않습니다." \
          "      [Info] setup does not auto-run sudo-based installs."
      fi
      msg \
        "      수동 설치: sudo apt-get update && sudo apt-get install -y python3-venv" \
        "      Manual install: sudo apt-get update && sudo apt-get install -y python3-venv"
      PREREQ_BLOCKED=1
    fi
  fi

  if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
    msg \
      "      [오류] pip/pip3 명령이 활성화되어 있지 않습니다." \
      "      [Error] pip/pip3 command is not available."
    msg \
      "      수동 설치: sudo apt-get update && sudo apt-get install -y python3-pip" \
      "      Manual install: sudo apt-get update && sudo apt-get install -y python3-pip"
    PREREQ_BLOCKED=1
  fi
}

has_tkinter() {
  python3 - <<'PY' >/dev/null 2>&1
import tkinter  # noqa: F401
PY
}

ensure_tkinter() {
  if ! command -v python3 >/dev/null 2>&1; then
    msg \
      "      [안내] python3 미탐지로 tkinter 점검을 건너뜁니다." \
      "      [Info] python3 not found, skipping tkinter check."
    return
  fi

  if has_tkinter; then
    msg "      tkinter: 사용 가능" "      tkinter: available"
    return
  fi

  msg "      [안내] tkinter 모듈이 없습니다." "      [Info] tkinter module is missing."
  msg \
    "      [중요] tkinter가 없으면 control_panel.exe GUI를 실행할 수 없습니다." \
    "      [Important] Without tkinter, control_panel.exe GUI cannot start."

  if [[ "$SETUP_AUTO_APT_INSTALL" == "1" ]] && apt_install_packages python3-tk && has_tkinter; then
    msg "      tkinter 자동 설치 완료" "      tkinter auto-install completed"
    return
  fi

  msg \
    "      [안내] setup에서는 sudo 권한 설치를 자동 수행하지 않습니다." \
    "      [Info] setup does not auto-run sudo-based installs."
  msg "      수동 설치:" "      Manual install:"
  msg \
    "      1) Windows 명령 프롬프트(cmd) 실행" \
    "      1) Open Windows Command Prompt (cmd)"
  msg \
    "      2) wsl 입력 후 Enter" \
    "      2) Run 'wsl' and press Enter"
  msg \
    "      3) WSL 셸에서: sudo apt-get update && sudo apt-get install -y python3-tk" \
    "      3) In WSL shell: sudo apt-get update && sudo apt-get install -y python3-tk"
  msg \
    "      4) 설치 후 exit 입력으로 WSL 종료" \
    "      4) After install, run 'exit' to leave WSL"
  msg \
    "      5) setup을 다시 실행하세요." \
    "      5) Run setup again."
}

ensure_node_stack() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi

  msg "      [안내] Node.js 또는 npm이 없습니다." "      [Info] Node.js or npm is missing."
  if ! command -v apt-get >/dev/null 2>&1; then
    msg \
      "      [오류] 자동 설치를 지원하지 않는 환경입니다." \
      "      [Error] Auto-install is not supported in this environment."
    msg \
      "      수동 설치: sudo apt-get update && sudo apt-get install -y nodejs npm" \
      "      Manual install: sudo apt-get update && sudo apt-get install -y nodejs npm"
    PREREQ_BLOCKED=1
    return 1
  fi

  if ! prompt_yes_no \
    "      Node.js/npm을 지금 자동 설치할까요? (Y/N): " \
    "      Install Node.js/npm automatically now? (Y/N): " \
    "N"; then
    msg "      [오류] Node.js/npm 설치가 필요합니다." "      [Error] Node.js/npm installation is required."
    msg \
      "      수동 설치: sudo apt-get update && sudo apt-get install -y nodejs npm" \
      "      Manual install: sudo apt-get update && sudo apt-get install -y nodejs npm"
    PREREQ_BLOCKED=1
    return 1
  fi

  if apt_install_packages nodejs npm && command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    msg "      Node.js/npm 자동 설치 완료" "      Node.js/npm auto-install completed"
    return 0
  fi

  msg "      [오류] Node.js/npm 자동 설치에 실패했습니다." "      [Error] Node.js/npm auto-install failed."
  msg \
    "      수동 설치: sudo apt-get update && sudo apt-get install -y nodejs npm" \
    "      Manual install: sudo apt-get update && sudo apt-get install -y nodejs npm"
  PREREQ_BLOCKED=1
  return 1
}

ensure_codex_cli() {
  if command -v codex >/dev/null 2>&1; then
    if codex --version >/dev/null 2>&1; then
      return 0
    fi
    msg \
      "      [오류] codex 명령은 있으나 정상 실행되지 않습니다." \
      "      [Error] codex command exists but does not run correctly."
    msg \
      "      Codex CLI 상태를 점검(재설치/재로그인)한 뒤 다시 실행하세요." \
      "      Check Codex CLI status (reinstall/relogin) and retry."
    PREREQ_BLOCKED=1
    return 1
  fi

  msg "      [오류] codex CLI가 PATH에 없습니다." "      [Error] codex CLI is not found in PATH."
  msg \
    "      Codex CLI는 설치뿐 아니라 로그인까지 필요해 자동 설치를 진행하지 않습니다." \
    "      Codex CLI requires installation and login; auto-install is not performed."
  msg \
    "      아래를 수동으로 완료한 뒤 setup_wsl.sh를 다시 실행하세요." \
    "      Complete the steps below manually, then rerun setup_wsl.sh."
  msg "      1) Codex CLI 설치" "      1) Install Codex CLI"
  msg "      2) codex login" "      2) codex login"
  msg "      3) codex --version 확인" "      3) Verify with codex --version"
  PREREQ_BLOCKED=1
  return 1
}

echo "========================================"
msg "소놀봇 WSL + Codex CLI 설정" "Sonolbot WSL + Codex CLI setup"
echo "========================================"
echo
msg "[1/5] 작업 폴더" "[1/5] Workspace"
echo "      $ROOT"
echo

msg "[2/5] 필수 도구 점검/설치" "[2/5] Checking/installing prerequisites"
ensure_python_stack || true
ensure_tkinter || true
ensure_node_stack || true
ensure_codex_cli || true

if [[ "$PREREQ_BLOCKED" -ne 0 ]]; then
  echo
  msg "[오류] 필수 조건이 충족되지 않았습니다." "[Error] Prerequisites are not fully satisfied."
  msg \
    "      위 안내대로 설치를 완료한 뒤 setup_wsl.sh를 다시 실행하세요." \
    "      Complete the steps above, then rerun setup_wsl.sh."
  exit 1
fi

echo "      python3: $(python3 --version 2>&1)"
if command -v pip >/dev/null 2>&1; then
  echo "      pip:     $(pip --version 2>&1)"
elif command -v pip3 >/dev/null 2>&1; then
  echo "      pip3:    $(pip3 --version 2>&1)"
fi
echo "      node:    $(node --version 2>&1)"
echo "      npm:     $(npm --version 2>&1)"
echo "      codex:   $(codex --version 2>&1 | head -n 1)"
echo

msg "[3/5] Python 의존성 설치" "[3/5] Installing Python dependencies"
if [[ ! -d "$VENV_DIR" ]]; then
  msg "      가상환경 생성: $VENV_DIR" "      Creating virtual environment: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
else
  msg "      기존 가상환경 사용: $VENV_DIR" "      Reusing existing virtual environment: $VENV_DIR"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT/requirements.txt"
msg "      완료" "      Done"
echo

add_missing_env_var() {
  local key="$1"
  local value="$2"
  if ! grep -Eq "^${key}=" "$ENV_FILE"; then
    printf "%s=%s\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

ensure_default_env_vars() {
  add_missing_env_var "SONOLBOT_ALLOWED_SKILLS" "sonolbot-telegram,sonolbot-tasks"
  add_missing_env_var "SONOLBOT_MULTI_BOT_MANAGER" "1"
  add_missing_env_var "SONOLBOT_BOT_WORKSPACES_DIR" "bots"
  add_missing_env_var "SONOLBOT_BOTS_CONFIG" ".control_panel_telegram_bots.json"
  add_missing_env_var "TELEGRAM_POLLING_INTERVAL" "1"
  add_missing_env_var "TELEGRAM_API_TIMEOUT_SEC" "20"
  add_missing_env_var "TELEGRAM_MESSAGE_RETENTION_DAYS" "7"
  add_missing_env_var "TELEGRAM_INCLUDE_24H_CONTEXT" "1"
  add_missing_env_var "TELEGRAM_MAX_FILE_BYTES" "52428800"

  add_missing_env_var "TASKS_DIR" "tasks"
  add_missing_env_var "LOGS_DIR" "logs"

  add_missing_env_var "DAEMON_POLL_INTERVAL_SEC" "1"
  add_missing_env_var "DAEMON_IDLE_TIMEOUT_SEC" "600"
  add_missing_env_var "LOG_RETENTION_DAYS" "7"
  add_missing_env_var "DAEMON_ACTIVITY_FILE" "logs/codex-app-server.log"
  add_missing_env_var "DAEMON_ACTIVITY_MAX_BYTES" "10485760"
  add_missing_env_var "DAEMON_ACTIVITY_BACKUP_COUNT" "7"
  add_missing_env_var "DAEMON_ACTIVITY_RETENTION_DAYS" "7"
  add_missing_env_var "DAEMON_TELEGRAM_FORCE_PARSE_MODE" "1"
  add_missing_env_var "DAEMON_TELEGRAM_DEFAULT_PARSE_MODE" "HTML"
  add_missing_env_var "DAEMON_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL" "1"

  add_missing_env_var "DAEMON_AGENT_REWRITER_ENABLED" "1"
  add_missing_env_var "DAEMON_AGENT_REWRITER_MODEL" "gpt-5.3-codex"
  add_missing_env_var "DAEMON_AGENT_REWRITER_TMP_ROOT" "/tmp/sonolbot-agent-rewriter"
  add_missing_env_var "DAEMON_AGENT_REWRITER_CLEANUP_TMP" "1"
  add_missing_env_var "DAEMON_AGENT_REWRITER_REASONING_EFFORT" "none"
  add_missing_env_var "DAEMON_AGENT_REWRITER_TIMEOUT_SEC" "40"
  add_missing_env_var "DAEMON_AGENT_REWRITER_REQUEST_TIMEOUT_SEC" "30"
  add_missing_env_var "DAEMON_AGENT_REWRITER_MAX_RETRY" "1"
  add_missing_env_var "DAEMON_AGENT_REWRITER_RESTART_BACKOFF_SEC" "2"

  add_missing_env_var "SONOLBOT_STORE_CODEX_SESSION" "1"
}

msg "[4/5] .env 확인" "[4/5] Checking .env"
if [[ -f "$ENV_FILE" ]]; then
  msg \
    "      .env 파일이 이미 존재합니다: $ENV_FILE" \
    "      .env already exists: $ENV_FILE"
  ensure_default_env_vars
  chmod 600 "$ENV_FILE" 2>/dev/null || true
else
  msg "      .env 파일을 새로 생성합니다." "      Creating a new .env file."

  cat > "$ENV_FILE" <<EOV
SONOLBOT_ALLOWED_SKILLS=sonolbot-telegram,sonolbot-tasks
SONOLBOT_MULTI_BOT_MANAGER=1
SONOLBOT_BOT_WORKSPACES_DIR=bots
SONOLBOT_BOTS_CONFIG=.control_panel_telegram_bots.json
TELEGRAM_POLLING_INTERVAL=1
DAEMON_POLL_INTERVAL_SEC=1
TELEGRAM_MAX_FILE_BYTES=52428800
DAEMON_ACTIVITY_MAX_BYTES=10485760
DAEMON_ACTIVITY_BACKUP_COUNT=7
DAEMON_TELEGRAM_FORCE_PARSE_MODE=1
DAEMON_TELEGRAM_DEFAULT_PARSE_MODE=HTML
DAEMON_TELEGRAM_PARSE_FALLBACK_RAW_ON_FAIL=1
DAEMON_AGENT_REWRITER_ENABLED=1
DAEMON_AGENT_REWRITER_MODEL=gpt-5.3-codex
DAEMON_AGENT_REWRITER_TMP_ROOT=/tmp/sonolbot-agent-rewriter
DAEMON_AGENT_REWRITER_CLEANUP_TMP=1
DAEMON_AGENT_REWRITER_REASONING_EFFORT=none
DAEMON_AGENT_REWRITER_TIMEOUT_SEC=40
DAEMON_AGENT_REWRITER_REQUEST_TIMEOUT_SEC=30
DAEMON_AGENT_REWRITER_MAX_RETRY=1
DAEMON_AGENT_REWRITER_RESTART_BACKOFF_SEC=2
SONOLBOT_STORE_CODEX_SESSION=1
EOV
  ensure_default_env_vars
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  msg "      .env 생성 완료: $ENV_FILE" "      .env created: $ENV_FILE"
fi
echo

msg "[5/5] 다음 단계" "[5/5] Next steps"
msg "  1) control_panel.exe 실행" "  1) Run control_panel.exe"
msg "  2) Telegram 다중 봇 설정에서 토큰/허용 사용자ID 등록 후 저장" "  2) Register bot token(s)/allowed user ID(s) in Telegram multi-bot settings and save"
msg "  3) 패널에서 Start 버튼으로 데몬 시작" "  3) Start daemon from panel with the Start button"
msg "  4) 공통 로그 확인: tail -f logs/daemon-\$(date +%F).log" "  4) Check common logs: tail -f logs/daemon-\$(date +%F).log"
echo
msg "설정 완료" "Setup complete"
