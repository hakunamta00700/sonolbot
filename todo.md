# Daemon Service 리팩토링 TODO

목표: `src/sonolbot/core/daemon/service.py`의 단일 클래스 책임을 줄이고, 설정/초기화 영역을 분리해 가독성·안정성을 높인다.

## 공통 규칙
- 각 항목 완료 시 즉시 체크(`- [x]`)하고 커밋한다.
- 수정 파일은 최소화하고, 기존 동작은 유지한다.
- 가능하면 작은 단위로 나눠 커밋한다.

## 진행

### 1) 준비
- [ ] [todo.md] 리팩토링 범위 및 단계 점검표 정리

### 2) 1차 추출: 초기화 설정 분리
- [ ] `src/sonolbot/core/daemon/service_config.py`에 `DaemonServiceConfig` 도입
  - env 파싱/기본값/클램프 정책을 한 곳에서 관리
  - `DAEMON_TELEGRAM_DEFAULT_PARSE_MODE`, 리라이터 프롬프트 파일 로딩 같은 입력 유효성 처리 포함
- [ ] `DaemonService.__init__`에서 env 파싱 직접 코드를 `DaemonServiceConfig`로 대체
  - 기존 `self.*` 초기값은 `config` 값을 주입받도록 변경
  - 동작 로그는 동일 메시지/레벨 유지
- [ ] `todo.md` 완료 체크 및 커밋

### 3) 공통 도우미 정리
- [ ] `service_utils`로 중복되는 유틸(파싱/문자 처리) 위임 정리
- [ ] `_env_int/_env_float/_env_bool` 역할 중 중복 정리
- [ ] `todo.md` 완료 체크 및 커밋

### 4) 리스크 점검/정리
- [ ] 변경으로 인해 env 파싱 분기 변경 여부 재확인(로그/클램프/기본값)
- [ ] 실패/예외 경로(파싱 실패, 경로 생성 실패) 동작 영향 점검
- [ ] `todo.md` 완료 체크 및 커밫
