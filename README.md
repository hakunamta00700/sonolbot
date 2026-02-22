# Sonolbot

텔레그램 봇 운영 자동화 프로젝트입니다.  
Windows + WSL 환경을 기준으로 `uv` 기반 패키지 구조와 `click` CLI로 정리된 상태입니다.

## 현재 리팩토링 상태 (요약)

- 프로젝트는 `uv` 기반 패키지 관리로 정리했습니다.
- 실행 진입점은 `sonolbot` CLI입니다.
- 설정/런타임 파일(`AGENTS*.md`, `.codex`)은 `agent_runtime/`로 이동했습니다.
- 배치/쉘 스크립트는 Python 기반 작업으로 일괄 정리했습니다.
- 의존성은 `pyproject.toml` 기준으로 관리하고, `requirements.txt`는 하위 호환용 최소 집합으로 유지합니다.

## 프로젝트 구조

```text
agent_runtime/
├─ AGENTS.md
├─ AGENTS__FOR_CODER.md
└─ .codex/                     (Codex 프롬프트/스킬 런타임)

docs/
logs/
packaging/
scripts/
src/sonolbot/
requirements.txt
pyproject.toml
todo.md
.env.example
```

## 실행 요구사항

- Windows 10/11
- WSL2 + Ubuntu
- Python 3.10+
- `uv` 설치
- Telegram Bot Token

## 설치/동기화

```bash
cd mybot_ver3_codex_zerosetting
uv sync --all-extras
```

`--all-extras`는 `pyproject.toml`의 선택 패키지 그룹을 함께 설치합니다.
원하면 기본(필수)만 설치하려면 `uv sync`로 진행할 수 있습니다.

## 사용법 (핵심)

### 1) 도움말

```bash
uv run sonolbot --help
uv run sonolbot --version
```

### 2) 환경 변수 생성

```bash
copy .env.example .env
```

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`는 필수입니다.
운영 시에는 `SONOLBOT_ALLOWED_SKILLS`, `LOGS_DIR`, `TASKS_DIR` 등도 설정합니다.

### 3) 초기 설정

```bash
uv run sonolbot setup wsl --auto-apt-install --skip-env   # WSL 의존성 정리
uv run sonolbot setup admin --panel                       # 초기 셋업 + 패널 실행 선택
uv run sonolbot setup configure-wsl-dns --networking-mode mirrored
```

### 4) 데몬 실행

```bash
uv run sonolbot check              # 수신 대기 점검
uv run sonolbot autoexecutor        # 기존 mybot_autoexecutor 진입점
uv run sonolbot daemon start        # 데몬 시작
uv run sonolbot daemon drain        # 미처리 메시지 1회 처리
```

### 5) 패널 실행

```bash
uv run sonolbot panel start
uv run sonolbot panel build-exe
```

### 6) 작업(Task) 명령

```bash
uv run sonolbot task list
uv run sonolbot task activate <task-id|keyword>
uv run sonolbot task list --json
```

### 7) 스킬 관리

```bash
uv run sonolbot skill list
uv run sonolbot skill install ./path/to/skill --force
```

설치 시 `SKILL.md`가 있는 경로만 스킬로 등록됩니다.

## 런타임/규칙 파일 위치

- 운영 안내 지침: `agent_runtime/AGENTS.md`
- 코드 작성 규칙: `agent_runtime/AGENTS__FOR_CODER.md`
- 코덱스 프롬프트/스킬: `agent_runtime/.codex`

Codex 대화에서 과거 `./.codex` 경로를 참조하던 내용은 이 위치로 이동되었습니다.

## 패키지/의존성 반영

현재 `pyproject.toml`은 필수/선택 의존성을 모두 선언합니다.

- 필수: `python-dotenv`, `requests`, `click`
- 선택:
  - `skills-core`: `defusedxml`, `lxml`
  - `skills-office`: `openpyxl`, `Pillow`
  - `skills-pdf`: `pypdf`, `pdf2image`
  - `skills-web`: `playwright`

## 로깅

```bash
tail -f logs/daemon-$(date +%F).log
tail -f logs/codex-app-server.log
```

## 자주 쓰는 점검 포인트

- `AGENTS.md`/`AGENTS__FOR_CODER.md`가 루트가 아닌 `agent_runtime/`에 있는지 확인
- `.codex`가 루트가 아닌 `agent_runtime/.codex`에 있는지 확인
- `uv run sonolbot --help`에서 현재 서브커맨드 목록이 정상인지 확인

## 참고

- GUI 패널 관련 스크립트와 실행 바이너리 관련 메타데이터는 `packaging/`에 정리되어 있습니다.
- 기존 문서(`실행방법.txt` 등)는 필요시 정렬 후 갱신해 두면 운영이 더 쉬워집니다.
