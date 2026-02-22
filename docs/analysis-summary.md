# 분석 요약

- Telegram 데몬은 멀티봇 매니저 + worker 구조로 동작한다.
- 런타임은 크게 메시지 수집/Codex 연결/응답 송신/상태관리로 구성된다.
- Telegram I/O와 task memory는 스킬 레이어로 분리되어 있으며, `skill_bridge`가 동적 결합한다.
- 운영상 핵심은 `.env`, `.control_panel_telegram_bots.json`, `tasks/`, `logs/`의 일관성이다.
- 리스크는 네트워크 장애 대응, 멀티봇 로그/리소스 증식, 동시성/권한 경합 관리다.
