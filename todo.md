# Daemon Service Refactor TODO

Goal: reduce responsibility concentration in `src/sonolbot/core/daemon/service.py` and improve maintainability.

Rules
- Mark items immediately when done: `- [x]`
- Keep changes focused and backward-compatible
- Commit after each completed section

Progress

## 1) Setup
- [x] Create `todo.md` and define refactor scope

## 2) Phase 1: Initialize config extraction
- [x] Add `src/sonolbot/core/daemon/service_config.py` with `DaemonServiceConfig`
  - Centralize env parsing, defaults, and clamping logic
  - Include validation for `DAEMON_TELEGRAM_DEFAULT_PARSE_MODE` and prompt file loading
- [x] Replace env parsing block in `DaemonService.__init__` with config loading
  - Set `self.*` runtime attributes from config values
  - Keep runtime behavior and warning messages equivalent
- [x] Mark phase complete in this TODO and commit

## 3) Phase 2: Utility boundary cleanup
- [x] Move small utilities to shared modules where possible (string/env helpers)
- [x] Remove duplicated `_env_*` parsing wrappers if no longer needed
- [x] Mark phase complete in this TODO and commit

## 4) Risk sweep
- [ ] Re-check edge cases: env parsing, parse mode fallback, path resolution
- [ ] Re-check exception paths and startup behavior
- [ ] Mark phase complete in this TODO and commit
