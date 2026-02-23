# Daemon Service Refactor TODO (Rebased v3)

Goal: reduce control-message duplication and Telegram transport branching risk in `src/sonolbot/core/daemon/service.py` while keeping behavior unchanged.

Rules
- Keep each step small and focused.
- Mark an item done immediately: `- [x]`
- For each task: implement -> test -> update todo -> commit.

## 1) Control reply pattern unification (Priority 1)
- [x] R1-1: Add `_send_control_reply(...)` helper in `DaemonService`
  - Centralize `telegram_send_text` + `_finalize_control_message_if_sent` + return value
  - Keep defaults compatible with current UI flow (`request_max_attempts=1`, optional `parse_mode`, optional keyboards)
- [x] R1-2: Use `_send_control_reply(...)` in `_forward_task_guide_edit_request`
  - Replace direct send/finalize pairs with helper
- [x] R1-3: Use `_send_control_reply(...)` in `_handle_single_control_message`
  - Replace repeated `sent = ...` + finalize call for simple control-message branches
- [x] R1-4: Run syntax check and commit

## 2) Telegram transport helper consolidation (Priority 2)
- [x] R2-1: Add internal `_telegram_send_text_once(...)` helper for raw payload send attempts
  - Single place for API fallback attempts (`send_text_*` family), including `TypeError` fallback and `exc` logging
  - Keep exact semantics for parse-mode selection and parse-fallback behavior
- [x] R2-2: Refactor `_telegram_send_text` and `_telegram_edit_message_text` to call the new helper
- [x] R2-3: Run syntax check and commit

## 3) Final validation checklist
- [ ] R3-1: Quick consistency pass for variable naming around control finalization
  - Ensure no new regression risk in `message_id`/`msg_id` usage at call sites touched by these changes
- [ ] R3-2: Run syntax check and final commit
