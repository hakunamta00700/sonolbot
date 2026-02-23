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
- [x] 커밋: `refactor: inject core runtime into DaemonService`

## 우선순위 10: Core 런타임 DI 테스트 안정화
- [x] 작업: `tests/test_service_core_runtime_di.py` 들여쓰기 문법 오류 수정
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "DaemonServiceCoreRuntime|_import_service_core|test_gui_session_detection_defaults_to_no_display_on_posix|import sys" tests/test_service_core_runtime_di.py`
- [x] 커밋: `test: fix service core runtime DI test indentation`

## 우선순위 11: Core 런타임 python 탐지 개선
- [x] 작업: `DaemonServiceCoreRuntime._detect_python_bin`에 Windows venv(`.venv\\Scripts\\python.exe`) 우선 탐지 추가
- [x] 테스트: `tests/test_service_core_runtime_di.py::TestDaemonServiceCoreRuntimeDI::test_init_core_runtime_prefers_workspace_venv_python`가 OS별 경로를 검증하도록 갱신
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "Scripts|python.exe|_detect_python_bin|os.name == \"nt\"|expected_python" src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): detect venv python path per platform`

## 우선순위 12: Core 런타임 env/GUI 세션 로직 분리
- [x] 작업: `DaemonServiceCoreRuntime`에 GUI 세션 판별을 `env` 의존형 유틸로 분리(`_build_default_env`, `_has_gui_session(env=...)`)
- [x] 작업: `DaemonServiceCoreRuntime`에 venv 후보 경로 생성 헬퍼 `_candidate_venv_python_paths(root)` 추가
- [x] 테스트: `test_init_core_runtime_defaults`에서 `SONOLBOT_GUI_SESSION` 기본 키 검증
- [x] 테스트: `test_init_core_runtime_builds_env_default_gui_session_marker` 추가
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "_build_default_env|_candidate_venv_python_paths|_has_gui_session\\(" src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): isolate gui session env and venv candidate builder`

## 우선순위 13: Core 런타임 env 정책 DI 주입
- [x] 작업: `DaemonServiceCoreEnvPolicy` 추가 및 `DaemonServiceCoreRuntime` 기본 env 생성을 정책 객체로 위임
- [x] 작업: `DaemonServiceCoreRuntime` 생성자에 `env_policy` 의존성 주입 파라미터 추가
- [x] 테스트: `tests/test_service_core_runtime_di.py`에서 정책 주입 시 `SONOLBOT_GUI_SESSION` 오버라이드 검증 테스트 추가
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py`
- [x] 테스트: `python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "DaemonServiceCoreEnvPolicy|env_policy|_import_service_core|test_injected_env_policy_overrides_default_env" src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): inject env policy for runtime defaults`

## 우선순위 14: DaemonService에서 env_policy 주입 파이프라인 정리
- [x] 작업: `src/sonolbot/core/daemon/service.py` 생성자에 `core_env_policy` 옵션 추가
- [x] 작업: `DaemonService`가 `_init_core_runtime(core_runtime, env_policy=core_env_policy)`로 초기화되도록 변경
- [x] 테스트: `tests/test_service_core_runtime_di.py`에서 `_init_core_runtime(env_policy=...)` 경로 검증
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service.py` (실행 완료)
- [x] 체크: `rg -n "core_env_policy|core_runtime, env_policy" src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): add core_env_policy to service ctor`

## 우선순위 15: Core 런타임 venv 후보 경로 추가
- [x] 작업: `DaemonServiceCoreRuntime._candidate_venv_python_paths`에 `python3`, `python3.exe` 후보 추가
- [x] 테스트: `test_init_core_runtime_prefers_workspace_venv_python`에서 다중 후보 생성해 기본 우선순위 유지 검증 유지
- [x] 테스트: `test_init_core_runtime_checks_venv_python_order` 추가 (주요 후보 미존재 시 보조 후보 선택)
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "python3|python3.exe|_candidate_venv_python_paths|test_init_core_runtime_checks_venv_python_order" src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): extend venv python candidates`

## 우선순위 16: Core 런타임 env setter 정규화
- [x] 작업: `DaemonServiceCoreRuntime`에 `set_env`/`_sanitize_env` 추가
- [x] 작업: `DaemonServiceCoreMixin.env` setter에서 런타임 `set_env` 사용
- [x] 테스트: `test_set_env_rebuilds_gui_session_marker` 추가
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "set_env\\(|_sanitize_env\\(|SONOLBOT_GUI_SESSION" src/sonolbot/core/daemon/service_core.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): normalize env updates through helper`

## 우선순위 17: Core 런타임 python 탐지 정책 DI
- [x] 작업: `DaemonServiceCorePythonPolicy` 생성 및 기본 venv 후보 전략 분리
- [x] 작업: `DaemonServiceCoreRuntime` 생성자에 `python_policy` 주입 추가
- [x] 작업: `DaemonServiceCoreMixin._init_core_runtime` 및 `DaemonService` 생성자에 python policy 주입 파라미터 추가
- [x] 테스트: `test_init_core_runtime_uses_python_policy` 추가
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py && python -m unittest tests/test_service_core_runtime_di.py`
- [x] 체크: `rg -n "DaemonServiceCorePythonPolicy|python_policy|build_venv_python_paths" src/sonolbot/core/daemon/service_core.py src/sonolbot/core/daemon/service.py tests/test_service_core_runtime_di.py`
- [x] 커밋: `refactor(core): inject python detection policy`
