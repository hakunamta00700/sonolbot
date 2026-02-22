# Sonolbot refactor todo progress
- [x] 1. 현재 의존성 분석 결과 정리
  - [x] 전체 파이썬 import 스캔 완료
  - [x] 핵심 런타임/선택형(skills) 의존성 분류 완료

- [ ] 2. uv 패키지 구조화
  - [ ] `pyproject.toml` 생성 (name=sonolbot, click 기반 entrypoint `sonolbot`)
  - [ ] 최소 런타임 의존성 정리 (dotenv, requests, click)
  - [ ] skills별 선택형 의존성 그룹 구성
  - [ ] `requirements.txt`와 정합성 점검

- [x] 3. 코어 실행 진입점 정비
  - [x] click CLI 그룹/하위 커맨드 설계 (`daemon`, `panel`, `task`, `skill`, `setup`)
  - [x] 기존 root 스크립트(quick_check/process_pending 등)와 연동

- [ ] 4. .codex/AGENTS 실행 위치 분리
  - [ ] 코딩에이전트 실행 기준 디렉터리 추가 (예: `agent_runtime/`)
  - [ ] `.codex` 경로 동적 해석(기본 root + `SONOLBOT_AGENT_HOME` fallback) 적용
  - [ ] `AGENTS.md`, `AGENTS__FOR_CODER.md`, `.codex` 동기화/이관 반영

- [x] 5. 배치/셸 스크립트 파이썬 전환
  - [x] setup_admin.bat -> `python` CLI로 이관
  - [x] setup_wsl.sh -> `python` CLI로 이관
  - [x] mybot_autoexecutor.sh -> `python` CLI로 이관
  - [x] setup[관리자권한으로실행].bat -> python 래퍼로 이관
  - [x] control_panel.bat -> `python` CLI로 이관
  - [x] build_control_panel_exe.bat -> `python` CLI로 이관
  - [ ] setup_messages.ps1, configure_wsl_dns.ps1 -> 파이썬 모듈로 대체(내부 유틸)
  - [x] 기존 `.bat`, `.sh`, `.ps1` 삭제

- [x] 6. 실행 파일/명령 정리
  - [x] `sonolbot` 커맨드에서 데몬/패널/체크/드레인/ID조회 가능
  - [x] `sonolbot skill list/install` 명령 구현
  - [x] `sonolbot task list/activate` 명령 구현

- [ ] 7. 마무리
  - [ ] `.gitignore`/문서 반영
  - [ ] 실행 예시 및 변환 내역 요약
