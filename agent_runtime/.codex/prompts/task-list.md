---
description: Sonolbot 전체 태스크 목록/상태 요약
argument-hint: "[limit 또는 검색어]"
---

Sonolbot 태스크 목록을 조회한다.

실행 규칙:
1. 인자(`$ARGUMENTS`)가 비어 있으면 기본 제한 50개로 조회:
   - `python3 -m sonolbot.tools.task_commands list --json --limit 50`
2. 인자가 숫자면 limit으로 간주:
   - `python3 -m sonolbot.tools.task_commands list --json --limit <숫자>`
3. 인자가 숫자가 아니면 검색어(keyword)로 간주:
   - `python3 -m sonolbot.tools.task_commands list --json --keyword "<인자>" --limit 50`

응답 형식:
- 전체 개수(`tasks_total`)와 표시 개수(`shown`)를 먼저 알려준다.
- 각 항목은 `msg_<id>`, 상태, 핵심 지시(instruction), 최근 결과 요약을 한 줄씩 간단히 보여준다.
- 사용자가 다음에 바로 활성화할 수 있도록 마지막 줄에 `/task-activate <msg_id>` 예시를 반드시 제시한다.



