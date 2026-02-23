# DaemonService refactor plan (v1)

목표: `src/sonolbot/core/daemon/service.py`의 prefix별 책임을 외부 모듈로 분리해 가독성과 테스트 가능성을 높이고, 앞으로 기능 단위로 injection(믹신 또는 외부 클래스) 형태로 확장할 수 있게 정리한다.

원칙
- 한 번에 한 개의 기능 덩어리만 이동
- 각 단계는 `작업 -> 작업완료 -> 테스트 -> 체크 -> 커밋` 순서로 진행
- 기존 동작 호환성 우선
- 큰 이동 이전에 `todo.md`에서 다음 단계 상태를 바로 갱신

## 1) 우선순위 1: Telegram 기능 분리 (`_telegram_*`)
- [x] 작업: `src/sonolbot/core/daemon/service_telegram.py`에 Telegram mixin 생성
- [x] 작업: `DaemonService`가 `DaemonServiceTelegramMixin`을 상속하도록 변경
- [x] 작업완료: `_normalize_telegram_parse_mode`, `_resolve_telegram_parse_mode`, `_sanitize_telegram_text_for_parse_mode`, `_get_telegram_runtime_skill`, `_escape_telegram_html`, `_telegram_get_me_name`, `_telegram_get_my_name`, `_telegram_set_my_name`, `_telegram_send_text_once`, `_telegram_send_text`, `_telegram_edit_message_text`, `_finalize_control_message`, `_finalize_control_message_if_sent`, `_send_control_reply`를 mixin으로 이동
- [ ] 테스트: 요청 없음(사용자 요청 시 별도 실행)
- [x] 체크: `rg -n "_normalize_telegram_parse_mode|_send_control_reply|_telegram_edit_message_text|class DaemonService" src/sonolbot/core/daemon/service.py src/sonolbot/core/daemon/service_telegram.py` 결과로 이전 메서드가 이동되었는지 확인
- [x] 커밋: `refactor: extract telegram helpers into mixin`

## 2) 우선순위 2: Task 기능 분리 (`_task_*`)
- [x] 작업: Task 관련 메서드를 `service_task.py`로 이동
- [x] 작업완료: `_get_task_skill`은 Task mixin으로 이동 (`_run_task_commands_json` 포함), Task 도메인 메서드 30+개 이관
- [x] 테스트: `python -m compileall src/sonolbot/core/daemon/service.py src/sonolbot/core/daemon/service_task.py`
- [x] 체크: `rg -n "^    def .*task" src/sonolbot/core/daemon/service.py src/sonolbot/core/daemon/service_task.py` 및 `_lookup_mapped_thread_id` 등 task 도메인 잔존 점검
- [x] 커밋: `refactor: extract task domain methods into mixin`

## 3) 우선순위 3: App 서버 기능 분리 (`_app_*`)
- [ ] 작업: App 서버 IPC/스레드/루프/세션 메서드를 `service_app.py`로 이동
- [ ] 작업완료: `DaemonService`의 책임도메인 분리 범위 정리
- [ ] 테스트: 요청 없음(사용자 요청 시 별도 실행)
- [ ] 체크: `_app_*` 호출부 위임 경로 정합성 확인
- [ ] 커밋: 작업 완료 후 순차 커밋

## 4) 우선순위 4: 채팅 릴리스/락 분리 (`_chat_lease_*`)
- [ ] 작업: chat lease 전용 로직을 별도 mixin으로 이동
- [ ] 작업완료: `_chat_lease_*`와 릴리스/터치/상태 계산 책임 분리
- [ ] 테스트: 요청 없음(사용자 요청 시 별도 실행)
- [ ] 체크: 상태 파일 경로/락 해제 동작 영향 없음 확인
- [ ] 커밋: 작업 완료 후 순차 커밋

## 5) 우선순위 5: Rewriter 기능 분리 (`_rewriter_*`)
- [ ] 작업: Agent rewriter 관련 메서드 분리
- [ ] 작업완료: `_rewriter_*` 동작을 외부 클래스 또는 mixin으로 위임
- [ ] 테스트: 요청 없음(사용자 요청 시 별도 실행)
- [ ] 체크: IPC 경로/로그 기록 부작용 점검
- [ ] 커밋: 작업 완료 후 순차 커밋

## 6) 우선순위 6: 기타 공통 헬퍼 정리
- [ ] 작업: `_send_control_reply` 의존성 최소화 및 중복 정리 마무리
- [ ] 작업완료: `todo.md` 진행표준을 유지하며 다음 단계 인덱스 반영
- [ ] 테스트: 요청 없음(사용자 요청 시 별도 실행)
- [ ] 체크: 전체 파일에서 prefix 기반 분리 이력 요약
- [ ] 커밋: 마무리 정리 완료 후 커밋
