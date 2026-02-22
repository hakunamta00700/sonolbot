# 프로젝트 전체 분석 (mybot_ver3_codex_zerosetting)

## 1) 한 줄 요약
이 저장소는 **Telegram 봇 데몬 + Codex 오케스트레이션 + 스킬 기반 I/O/태스크 메모리 + 멀티봇 관리**를 결합한 운영형 봇 플랫폼이다.

- 핵심 런타임: `daemon_service.py`
- Telegram I/O 스킬: `.codex/skills/sonolbot-telegram/scripts/telegram_io.py`
- 태스크/메모리 스킬: `.codex/skills/sonolbot-tasks/scripts/task_memory.py`
- 동적 스킬 연결: `skill_bridge.py`
- 다중 봇 UI/관리: `daemon_control_panel.py`

## 2) 아키텍처 정리

### 실행 엔트리 포인트
- `daemon_service.py`에서 실행 모드를 결정한다.
  - `DAEMON_BOT_WORKER=1` → 단일 봇 worker (`DaemonService`)
  - 기본(`SONOLBOT_MULTI_BOT_MANAGER=true`) → `MultiBotManager`가 여러 봇을 워커로 기동
  - 단일 데몬 fallback

### 메시지 처리 루프
1. Telegram polling으로 대기 메시지 수집
2. 작업 메모리/컨텍스트 구성
3. Codex 앱 서버와 연동해 응답 생성
4. Telegram 메시지 발송, 진행상태/완료상태 보강

### 멀티봇 동작
- `.control_panel_telegram_bots.json`(및 스크립트 유틸)을 통해 봇 등록/활성/설정 관리
- 워커 단위 pid/lock/격리 디렉터리로 독립 실행
- 예기치 못한 종료 시 backoff 재시작 루프 운영

## 3) 주요 컴포넌트

### A. daemon_service.py
- 데몬 생명주기, PID/락, 로깅, 프로세스 제어
- Telegram runtime 연동, Codex 실행/재시작 제어
- 스레드/채팅 상태(레이스 제어, idle/lease), 임계치 시간관리
- `drain_pending_once`, `run`, `_run_main_cycle` 등으로 처리 루프 구성
- 문서 정합성 점검 유틸(`check_docs_alignment.py`) 연계

### B. skill_bridge.py
- 동적 임포트 방식으로 skill 스크립트 로드
- 허용 스킬 목록을 환경변수로 제한 가능
- Telegram/Task runtime 객체를 데몬에 주입

### C. Telegram 스킬 (`sonolbot-telegram`)
- API fallback(host/domain) 및 전송 재시도/백오프
- 메시지 큐/중복 전송 방지/민감정보 로그 redaction
- 파일/음성/문서/이미지 처리
- 24시간 컨텍스트 빌드 지원

### D. Tasks 스킬 (`sonolbot-tasks`)
- thread 중심 폴더 구조의 작업 상태 관리
- `INSTRUNCTION.md` 동기화, `index.json` 관리
- 작업 변경 추적/검색/압축 패킷 생성
- legacy(`msg_*`) 읽기 호환성

### E. 제어판 (`daemon_control_panel.py`)
- 봇 등록/삭제/활성 제어, 상태조회
- 로그 뷰어, 자동시작, 재시작 옵션
- Codex/리라이터 설정, 봇별 메타데이터 편집

## 4) 주변 스크립트/운영 보조
- `process_pending.py`, `quick_check.py`: 작업 대기 상태 확인/1회 처리 루틴
- `scripts/*`: 토큰 검증, bot config migration, task migration, DNS/setup 유틸
- `setup_admin.bat`, `setup_wsl.sh`, `mybot_autoexecutor.sh`: 배포/실행 절차 보조

## 5) 데이터/상태 저장
- 운영 상태: `logs/`, 봇별 작업 로그
- 태스크 데이터: `tasks/chat_<chat_id>/thread_<thread_id>/`
- 봇 레지스트리: `.control_panel_telegram_bots.json`
- 환경설정: `.env`

## 6) 보안·안정성 포인트
- 토큰은 코드/로그 하드코딩 금지, `.env` 관리
- API 실패 시 fallback/재시도 로직 존재
- PID/락 기반 다중 실행 억제
- 네트워크/폴링 의존성으로 인해 외부 장애 복원성 점검 필요

## 7) 주요 리스크
- 다중봇 동작 시 디스크 증식(로그·tasks)과 프로필/격리 경계 관리
- polling 지연이 응답 체감 성능에 영향
- 핵심 종속성이 상대적으로 적어 버전 고정 관리 필요(재현성)
- 파일 기반 동기화 특성상 동시성/권한 이슈 점검 필수

## 8) 빠른 체크리스트
- `.env` 필수값 완비 여부
- `.control_panel_telegram_bots.json` 활성 bot 유효성(토큰/user)
- 워커별 로그/리소스 사용량 모니터링
- `scripts/check_docs_alignment.py` 주기 실행
- 백업/로그 보관 정책 수립
