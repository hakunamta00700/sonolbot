# daemon/service.py 由ы뙥?좊쭅 怨꾪쉷

紐⑺몴: `DaemonService`??`rewriter_*` 梨낆엫???쇳빀 ?대옒???대? 硫ㅻ쾭 吏묓빀?먯꽌 `Runtime` ?대옒?ㅻ줈 遺꾨━?섍퀬, `DaemonService`媛 二쇱엯 媛?ν븳 ?뺥깭濡??숈옉?섍쾶 ?뺣━.

洹쒖튃
- ?곗꽑?쒖쐞 ?쒖꽌濡?泥섎━?쒕떎.
- 媛??⑥쐞??`?묒뾽 -> ?묒뾽?꾨즺 -> ?뚯뒪??-> 泥댄겕 -> 而ㅻ컠` ?쒖꽌濡?異붿쟻?쒕떎.
- `daemon` ?숈옉 ?명솚?깆쓣 ?곗꽑?쒕떎.

## ?곗꽑?쒖쐞 1: Rewriter Runtime DI 湲곕컲 遺꾨━ (?ㅽ뻾)
- [x] ?묒뾽: `src/sonolbot/core/daemon/service_rewriter.py`??`DaemonServiceRewriterRuntime` ?대옒??異붽?
- [x] ?묒뾽: ?고??꾩씠 蹂댁쑀??`rewriter_*` ?곹깭瑜?`DaemonServiceRewriterRuntime`濡??대룞 (`proc/lock/request queue/log/threads/state`)
- [x] ?묒뾽: `_load_agent_rewriter_state`, `_save_agent_rewriter_state`瑜??고????곹깭 濡쒕뵫/??μ쑝濡??꾩엫
- [x] ?묒뾽: `_read_pid_file`, `_is_codex_app_server_pid`, `_acquire_agent_rewriter_lock`, `_release_agent_rewriter_lock`, `_build_codex_app_server_cmd`, `_write_agent_rewriter_log`, `_secure_file` ?꾩엫 ?명꽣?섏씠??異붽?
- [x] ?묒뾽?꾨즺: `DaemonServiceRewriterMixin`??`rewriter_*` ?띿꽦 ?꾨줈?쇳떚 ?꾩엫???먯뼱 湲곗〈 `_rewriter_*` 濡쒖쭅 蹂???놁씠 ?고????곹깭 ?묎렐
- [x] ?뚯뒪?? `python -m py_compile src/sonolbot/core/daemon/service_rewriter.py src/sonolbot/core/daemon/service.py`
- [x] 泥댄겕: `rg -n "self\\._rewriter_runtime_component|self\\.rewriter_"`濡?`service_rewriter.py`?먯꽌 ?꾩엫 寃쎈줈媛 ?쇨??섎뒗吏 ?뺤씤
- [ ] 而ㅻ컠: `refactor: split rewriter runtime state and inject via host service`

## ?곗꽑?쒖쐞 2: DaemonService ?앹꽦??二쇱엯 ?ъ씤???뺣━
- [x] ?묒꾩? `src/sonolbot/core/daemon/service.py` ?앹꽦?먯꿊 ?꾩씠?`rewriter_runtime`)
- [x] ?묒뾽?꾨즺: `_init_rewriter_runtime(rewriter_runtime)`瑜??듯빐 湲곕낯 ?고???二쇱엯 ?고???紐⑤몢 ?섏슜
- [x] ?뚯뒪?? `python -m py_compile src/sonolbot/core/daemon/service.py`
- [ ] 泥댄겕: `DaemonService()` 湲곕낯 ?ㅽ뻾怨?`DaemonService(rewriter_runtime=...)` ?쒓렇?덉쿂 ?곹뼢 寃??- [ ] 而ㅻ컠: `refactor: inject rewriter runtime into DaemonService`

## ?곗꽑?쒖쐞 3: ?ㅼ쓬 ?④퀎 以鍮?(App/lock/濡쒓렇 ?ы띁 ?뺣━)
- [ ] ?묒뾽: `_write_app_server_log`, `_secure_file` ??怨듭슜 ?ы띁???뚯쑀沅?遺꾨━ ?꾨낫 ?꾩텧
- [ ] ?묒뾽?꾨즺: app ?쒕쾭 helper 誘명빐寃???ぉ 紐⑸줉 ?뺣━
- [ ] ?뚯뒪?? ??由щ씪?댄꽣 ?몃뱾留?寃쎈줈???꾩슂???ы띁 ?꾨씫 ?뺤씤
- [ ] 泥댄겕: ?ㅼ쓬 ?④퀎 泥댄겕由ъ뒪???묒꽦
- [ ] 而ㅻ컠: `chore: prepare app helper migration follow-up`

﻿# daemon/service.py 리팩토링 TODO (DI 재설계)

## 규칙
- 한 번에 한 개 작업씩 진행: `작업 -> 작업완료 -> 테스트 -> 체크 -> 커밋`
- 각 단계는 우선순위 기준으로 진행
- 가능한 기존 동작 호환 유지

## 우선순위 1: Rewriter Runtime DI 분리
- [x] 작업: `src/sonolbot/core/daemon/service_rewriter.py`에 `DaemonServiceRewriterRuntime` 생성
- [x] 작업: `_rewriter_*` 상태값을 런타임으로 이동 (`proc / lock / queue / state / log / thread`)
- [x] 작업: `_load_agent_rewriter_state`, `_save_agent_rewriter_state` 위임
- [x] 작업: `_read_pid_file`, `_is_codex_app_server_pid`, `_acquire_agent_rewriter_lock`, `_release_agent_rewriter_lock`, `_build_codex_app_server_cmd`, `_write_agent_rewriter_log`, `_secure_file` 등 런타임 위임
- [x] 작업완료: `DaemonServiceRewriterMixin`에서 `rewriter_*` 접근을 runtime 프로퍼티로 위임 정리
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service_rewriter.py src/sonolbot/core/daemon/service.py`
- [x] 체크: `rg -n "self\\._rewriter_runtime_component|self\\.rewriter_" src/sonolbot/core/daemon/service_rewriter.py`
- [x] 커밋: `refactor: split rewriter runtime state and inject via host service`

## 우선순위 2: DaemonService 생성자 DI
- [x] 작업: `src/sonolbot/core/daemon/service.py` 생성자에 `rewriter_runtime` 주입 인자 추가
- [x] 작업완료: `_init_rewriter_runtime(rewriter_runtime)` 호출로 기본/주입 런타임 처리
- [x] 테스트: `python -m py_compile src/sonolbot/core/daemon/service.py`
- [x] 체크: `DaemonService` 시그니처 및 런타임 주입 초기화 호출 확인
- [ ] 커밋: `refactor: inject rewriter runtime into DaemonService`

## 우선순위 3: App/락/로그 헬퍼 정리(후속)
- [ ] 작업: App/lock/로그 헬퍼 소유권 분리 대상 식별
- [ ] 작업완료: `daemon/service_app.py` 계열로 이동 후보 정리
- [ ] 테스트: 대상 파일 컴파일 및 참조 점검
- [ ] 체크: `service.py`에서 미완료 `_app_*` 책임 정리
- [ ] 커밋: `chore: split app-related helpers`
