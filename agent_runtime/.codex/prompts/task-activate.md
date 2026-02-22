---
description: 특정 태스크 활성화(지침 읽기 + 상태 확인)
argument-hint: "<message_id | msg_ID | 검색어>"
---

Sonolbot 특정 태스크를 활성화하고 작업 준비 상태를 만든다.

필수 절차:
1. 인자(`$ARGUMENTS`)가 비어 있으면 즉시 사용자에게 `message_id/msg_ID/검색어` 입력을 요청한다.
2. 인자가 있으면 아래 명령으로 태스크를 조회한다.
   - `python3 scripts/task_commands.py activate "$ARGUMENTS" --json --include-instrunction`
3. 결과가 `ok=false`면:
   - 태스크를 찾지 못했다고 알리고 `/task-list` 실행을 안내한다.
4. 결과가 `ok=true`면:
   - 해당 태스크의 `INSTRUNCTION.md`(또는 fallback `INSTRUCTIONS.md`)를 읽은 것으로 간주하고 작업 준비 완료로 표시한다.
   - 아래를 간단히 요약한다:
     - task id (`msg_<id>`)
     - 상태(status)
     - 핵심 지시(instruction)
     - 최근 변경(latest_change)
     - 관련 태스크 IDs(있을 때만)
     - Codex session id(있을 때만)

마지막 응답 규칙:
- 2~5줄로 현재 태스크 목적을 짧게 요약한다.
- 마지막 문장은 반드시 사용자에게 다음 작업 지시를 묻는다.
- 예: `이 태스크에서 제가 바로 진행할 작업이 있나요?`

