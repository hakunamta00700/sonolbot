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
- [x] 커밋: `refactor: inject app runtime into DaemonService`


## 우선순위 4: DI 테스트 고정
- [x] 작업: `tests/test_service_app_runtime_di.py` 추가 (app 런타임 주입/상태/영속화 위임)
- [x] 작업완료: `DaemonServiceAppMixin`에서 `app_runtime` 주입 및 위임 동작 단위 검증
- [x] 테스트: `python -m unittest tests/test_service_app_runtime_di.py` (의존성 미설치 환경에서는 스킵 처리)
- [x] 체크: `rg -n "_init_app_runtime|_save_app_server_state|_set_runtime_env" tests/test_service_app_runtime_di.py`; 테스트는 현재 `dotenv` 부재로 import 스킵 상태에서 1건 skipped
- [x] 커밋: `test: add daemon app runtime injection unit tests`



## 우선순위 5: 테스트 의존성 안정화
- [x] 작업: `tests/test_service_app_runtime_di.py`에서 `dotenv` 의존성 누락 시 대체 스텁 로딩 적용
- [x] 테스트: `python -m unittest tests/test_service_app_runtime_di.py` (실제 4개 테스트 통과)
- [x] 체크: `rg -n "_ensure_fake_dotenv|_import_service_app|daemon service app runtime dependency" tests/test_service_app_runtime_di.py`
- [x] 커밋: `test: make app runtime DI tests runnable without optional env deps`

## 우선순위 6: Lease 런타임 DI 정리
- [x] 작업: `DaemonServiceLeaseRuntime` 생성 및 `daemon/service.py`에 `lease_runtime` 주입 경로 추가
- [x] 작업: `DaemonServiceLeaseMixin` 멤버(`_owned_chat_leases`, `_chat_lease_busy_logged_at`, `completed_message_ids_recent`, `_completed_requeue_log_ts`)를 런타임 속성으로 위임
- [x] 테스트: `tests/test_service_lease_runtime_di.py` 추가 및 완료 메시지 캐시/런타임 주입 검증
- [x] 체크: `rg -n "_init_lease_runtime|_get_lease_runtime|completed_message_ids_recent|_completed_requeue_log_ts" src/sonolbot/core/daemon/service.py src/sonolbot/core/daemon/service_lease.py tests/test_service_lease_runtime_di.py`
- [x] 커밋: `refactor: inject lease runtime state into DaemonService`

## 우선순위 7: Task 런타임 DI 정리
- [x] 작업: `DaemonServiceTaskRuntime` 생성 및 `daemon/service.py` 생성자에 `task_runtime` 주입 추가
- [x] 작업: `DaemonServiceTaskMixin._get_task_skill` 런타임 위임 재구성 (`_task_skill` 제거)
- [x] 테스트: `tests/test_service_task_runtime_di.py` 추가 (기본 런타임 생성/주입/캐시 동작 검증)
- [x] 체크: `rg -n "_task_runtime_component|_init_task_runtime|_get_task_runtime" src/sonolbot/core/daemon/service_task.py src/sonolbot/core/daemon/service.py tests/test_service_task_runtime_di.py`
- [x] 커밋: `refactor: inject task runtime into DaemonService`

## 우선순위 8: Telegram 런타임 DI 정리
- [x] 작업: `DaemonServiceTelegramRuntime` 생성 및 `daemon/service.py` 생성자에 `telegram_runtime` 주입 추가
- [x] 작업: `DaemonServiceTelegramMixin._get_telegram_runtime_skill` 런타임 위임 재구성 (`_telegram_runtime`/`_telegram_skill` 제거)
- [x] 테스트: `tests/test_service_telegram_runtime_di.py` 추가 (기본 런타임 생성/주입/캐시 동작 검증)
- [x] 체크: `rg -n "_telegram_runtime_component|_init_telegram_runtime|_get_telegram_runtime" src/sonolbot/core/daemon/service_telegram.py src/sonolbot/core/daemon/service.py tests/test_service_telegram_runtime_di.py`
- [x] 커밋: `refactor: inject telegram runtime into DaemonService`

## 우선순위 9: Core 런타임 DI 정리
- [x] 작업: `DaemonServiceCoreRuntime` 추가 및 `daemon/service.py` 생성자에 `core_runtime` 주입 추가
- [x] 작업: `DaemonServiceCoreMixin`로 `python_bin/env/stop_requested/codex_*` 멤버 위임 정리
- [x] 테스트: `tests/test_service_core_runtime_di.py` 추가 (기본 런타임 생성/주입/필드 위임 검증)
- [x] 체크: `rg -n "_core_runtime_component|_init_core_runtime|_get_core_runtime|env = self.env" src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py`
- [ ] 커밋: `refactor: inject core runtime into DaemonService`
