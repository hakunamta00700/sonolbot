# daemon/service.py 리팩토링 TODO (DI 재설계)

## 규칙
- 한 번에 한 개 작업씩 진행: `작업 -> 작업완료 -> 테스트 -> 체크 -> 커밋`
- 각 단계는 우선순위 순서대로 진행
- 가능한 기존 동작 호환 유지

## 우선순위 1: Rewriter Runtime DI 분리
- [x] 작업: `src/sonolbot/core/daemon/service_rewriter.py`에 `DaemonServiceRewriterRuntime` 생성
- [x] 작업: `rewriter_*` 상태값을 런타임으로 이동 (`proc / lock / request queue / log / thread / state`)
- [x] 작업: `_load_agent_rewriter_state`, `_save_agent_rewriter_state` 위임
- [x] 작업: `_read_pid_file`, `_is_codex_app_server_pid`, `_acquire_agent_rewriter_lock`, `_release_agent_rewriter_lock`, `_build_codex_app_server_cmd`, `_write_agent_rewriter_log`, `_secure_file` 런타임 위임
- [x] 작업완료: `DaemonServiceRewriterMixin`에서 `rewriter_*` 접근을 런타임 프로퍼티로 위임
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_rewriter.py src/sonolbot/core/daemon/service.py`
- [x] 체크: `rg -n "self\._rewriter_runtime_component|self\.rewriter_" src/sonolbot/core/daemon/service_rewriter.py`
- [x] 커밋: `refactor: split rewriter runtime state and inject via host service`

## 우선순위 2: DaemonService 생성자 DI
- [x] 작업: `src/sonolbot/core/daemon/service.py` 생성자에 `rewriter_runtime` 주입 인자 추가
- [x] 작업완료: `_init_rewriter_runtime(rewriter_runtime)` 호출로 기본/주입 런타임 처리
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service.py`
- [x] 체크: `DaemonService` 시그니처 및 런타임 주입 초기화 호출 확인
- [x] 커밋: `refactor: inject rewriter runtime into DaemonService`

## 우선순위 3: App 런타임 DI 정리
- [x] 작업: `DaemonServiceAppRuntime` 추가 및 app 상태/락/queue/log/session 유틸 분리
- [x] 작업: `DaemonServiceAppMixin`에 `app_*` 상태 프로퍼티, app 관련 helper 래핑 추가
- [x] 작업완료: `DaemonService` 생성자에서 `app_runtime` 주입 받도록 변경
- [x] 작업완료: `DaemonService`/`service_app` 동작 일관성 정리 완료(초기화 주입 흐름 검토)
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_app.py src/sonolbot/core/daemon/service.py`
- [x] 체크: `rg -n "self\._app_runtime_component|self\.app_" src/sonolbot/core/daemon/service_app.py src/sonolbot/core/daemon/service.py`
- [ ] 커밋: `refactor: inject app runtime into DaemonService`
