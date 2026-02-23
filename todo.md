# Daemon Service Refactor TODO (Rebased v4)

Goal: reduce duplication and reduce control/queueing risk in `src/sonolbot/core/daemon/service.py` while keeping behavior unchanged.

Rules
- Keep each step small and focused.
- Mark each item done immediately: `- [x]`
- For each task: implement -> test -> update todo -> commit.

## 1) Control reply pattern unification (Priority 1)
- [x] R1-1: Add `_send_control_reply(...)` helper in `DaemonService`
  - Centralize `telegram_send_text` + `_finalize_control_message_if_sent` + return value.
  - Keep defaults compatible with current UI flow (`request_max_attempts=1`, optional `parse_mode`, optional keyboards).
- [x] R1-2: Use `_send_control_reply(...)` in `_forward_task_guide_edit_request`
  - Replace direct send/finalize pairs with helper.
- [x] R1-3: Use `_send_control_reply(...)` in `_handle_single_control_message`
  - Replace repeated `sent = ...` + finalize call for simple control-message branches.
- [x] R1-4: Run syntax check and commit.

## 2) Telegram transport helper consolidation (Priority 2)
- [x] R2-1: Add internal `_telegram_send_text_once(...)` helper for raw payload send attempts
  - Single place for API fallback attempts (`send_text_*` family), including `TypeError` fallback and `exc` logging.
  - Keep exact semantics for parse-mode selection and parse-fallback behavior.
- [x] R2-2: Refactor `_telegram_send_text` and `_telegram_edit_message_text` to call the new helper.
- [x] R2-3: Run syntax check and commit.

## 3) Final validation checklist
- [x] R3-1: Quick consistency pass for variable naming around control finalization.
  - Ensure no new regression risk in `message_id`/`msg_id` usage at call sites touched by these changes.
- [x] R3-2: Run syntax check and final commit.

## 4) Queue deduplication cleanup (Priority 3)
- [ ] R4-1: Add reusable `_dedupe_messages_by_message_id(...)` helper
  - Centralize repeated merge-dedupe loops on `message_id` and skip invalid IDs safely.
- [ ] R4-2: Apply helper in `_handle_single_control_message` temp-task seed branch
  - Replace manual dedupe loop when combining `queued_messages` + temp seed messages.
- [ ] R4-3: Apply helper in `_app_process_cycle` queued merge branches
  - Replace manual dedupe loops in active-turn and initial turn batching paths.
- [ ] R4-4: Run syntax check and commit.
