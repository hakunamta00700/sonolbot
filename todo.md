# Daemon Service Refactor TODO (Rebased)

Goal: split `src/sonolbot/core/daemon/service.py` responsibilities so each section is easier to maintain and safer to change.

Rules
- Keep each step small and focused.
- Mark an item done immediately: `- [x]`
- After each task: `test -> check todo -> commit`.

## 1) Phase 1: Duplicate persistence logic cleanup (Priority 1)
- [x] P1-1: Add shared JSON state helpers in `src/sonolbot/core/daemon/service_utils.py`
  - Add helper to read `<state>.json` safely.
  - Add helper to build thread-state payloads.
  - Add helper to write state payloads safely.
- [x] P1-2: Refactor `_load_app_server_state` / `_save_app_server_state` to use shared helpers
- [x] P1-3: Refactor `_load_agent_rewriter_state` / `_save_agent_rewriter_state` to use shared helpers
- [x] P1-4: Run syntax check and commit phase completion

## 2) Phase 2: Logging helper cleanup (Priority 2)
- [x] P2-1: Add shared timestamped log append helper in `service_utils.py`
- [x] P2-2: Refactor `_write_app_server_log` / `_write_agent_rewriter_log` to use shared helper
- [x] P2-3: Keep behavior identical; run syntax check and commit

## 3) Phase 3: Interaction boundary cleanup (Priority 3)
- [ ] P3-1: Review large command handlers and extract any new helper candidates
- [ ] P3-2: Move repeated task-card rendering blocks into dedicated helper(s)
- [ ] P3-3: Run syntax check and commit

## 4) Phase 4: Risk sweep
- [x] R1: Re-check env/parse-mode startup edges (including missing/invalid prompt files)
- [ ] R2: Re-check exception paths around persistence/logging startup
- [ ] R3: Final checklist + commit
