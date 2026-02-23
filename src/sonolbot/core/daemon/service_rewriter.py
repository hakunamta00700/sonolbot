from __future__ import annotations

from sonolbot.core.daemon.runtime_shared import *


class DaemonServiceRewriterMixin:

    def _rewriter_is_running(self) -> bool:
        return self.rewriter_proc is not None and self.rewriter_proc.poll() is None

    def _rewriter_send_json(self, payload: dict[str, Any]) -> bool:
        if not self._rewriter_is_running() or self.rewriter_proc is None or self.rewriter_proc.stdin is None:
            return False
        rendered = json.dumps(payload, ensure_ascii=False)
        with self.rewriter_json_send_lock:
            try:
                self.rewriter_proc.stdin.write(rendered + "\n")
                self.rewriter_proc.stdin.flush()
                self._write_agent_rewriter_log("SEND", rendered)
                return True
            except Exception as exc:
                self._log(f"WARN: agent-rewriter send failed: {exc}")
                return False

    def _rewriter_notify(self, method: str, params: dict[str, Any] | None = None) -> bool:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        return self._rewriter_send_json(payload)

    def _rewriter_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._rewriter_is_running():
            return None

        with self.rewriter_req_lock:
            req_id = self.rewriter_next_request_id
            self.rewriter_next_request_id += 1
            response_q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self.rewriter_pending_responses[req_id] = response_q

        payload: dict[str, Any] = {"id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        if not self._rewriter_send_json(payload):
            with self.rewriter_req_lock:
                self.rewriter_pending_responses.pop(req_id, None)
            return None

        wait_sec = timeout_sec if timeout_sec is not None else self.agent_rewriter_request_timeout_sec
        try:
            reply = response_q.get(timeout=max(1.0, float(wait_sec)))
        except queue.Empty:
            self._log(f"WARN: agent-rewriter request timeout method={method} id={req_id}")
            with self.rewriter_req_lock:
                self.rewriter_pending_responses.pop(req_id, None)
            return None

        if "error" in reply:
            self._log(f"WARN: agent-rewriter request error method={method} id={req_id} error={reply.get('error')}")
            return None
        result = reply.get("result")
        if isinstance(result, dict):
            return result
        return {"value": result}

    def _rewriter_handle_server_request(self, request_obj: dict[str, Any]) -> None:
        req_id = request_obj.get("id")
        method = str(request_obj.get("method") or "")
        params = request_obj.get("params")
        payload: dict[str, Any]

        if method == "item/commandExecution/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/fileChange/requestApproval":
            payload = {"id": req_id, "result": {"decision": "accept"}}
        elif method == "item/tool/requestUserInput":
            payload = {
                "id": req_id,
                "result": self._resolve_tool_user_input_answers(params if isinstance(params, dict) else {}),
            }
        elif method == "item/tool/call":
            payload = {
                "id": req_id,
                "result": {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": "dynamic tool call is not supported by this daemon bridge",
                        }
                    ],
                },
            }
        elif method == "execCommandApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        elif method == "applyPatchApproval":
            payload = {"id": req_id, "result": {"decision": "approved"}}
        else:
            payload = {"id": req_id, "result": {}}
            self._log(f"WARN: unhandled agent-rewriter request method={method}, replied with empty result")

        if not self._rewriter_send_json(payload):
            self._log(f"WARN: failed to send agent-rewriter request response method={method} id={req_id}")

    def _rewriter_dispatch_incoming(self, line: str) -> None:
        self._write_agent_rewriter_log("RECV", line)
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            self._log(f"WARN: non-json agent-rewriter output: {line[:180]}")
            return
        if not isinstance(obj, dict):
            return

        if "id" in obj and ("result" in obj or "error" in obj):
            req_id = obj.get("id")
            with self.rewriter_req_lock:
                pending_q = self.rewriter_pending_responses.pop(req_id, None)
            if pending_q is not None:
                try:
                    pending_q.put_nowait(obj)
                except Exception:
                    pass
            return

        method = obj.get("method")
        if not isinstance(method, str):
            return

        if "id" in obj:
            self._rewriter_handle_server_request(obj)
            return

        try:
            self.rewriter_event_queue.put_nowait(obj)
        except Exception:
            self._log("WARN: agent-rewriter event queue full; dropping event")

    def _rewriter_stdout_reader(self) -> None:
        proc = self.rewriter_proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._rewriter_dispatch_incoming(line)

    def _rewriter_stderr_reader(self) -> None:
        proc = self.rewriter_proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            line = raw.rstrip("\n")
            if not line:
                continue
            self._write_agent_rewriter_log("ERR", line)
            if "ERROR" in line or "WARN" in line:
                self._log(f"[agent-rewriter][stderr] {line}")

    def _rewriter_process_notification(self, event: dict[str, Any]) -> None:
        method = str(event.get("method") or "")
        params = event.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "codex/event/task_complete":
            msg = params.get("msg")
            if not isinstance(msg, dict):
                return
            turn_id = str(msg.get("turn_id") or params.get("id") or "").strip()
            if not turn_id:
                return
            last_text = str(msg.get("last_agent_message") or "").strip()
            self.rewriter_turn_results[turn_id] = {
                "status": "completed",
                "text": last_text,
                "updated_at": time.time(),
            }
            return

        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                return
            turn_id = str(turn.get("id") or "").strip()
            if not turn_id:
                return
            status = str(turn.get("status") or "").strip().lower() or "completed"
            current = self.rewriter_turn_results.get(turn_id, {})
            if not isinstance(current, dict):
                current = {}
            current.setdefault("text", "")
            current["status"] = status
            current["updated_at"] = time.time()
            self.rewriter_turn_results[turn_id] = current
            return

    def _rewriter_drain_events(self, max_items: int = 200) -> None:
        for _ in range(max_items):
            try:
                event = self.rewriter_event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._rewriter_process_notification(event)
            except Exception as exc:
                self._log(f"WARN: agent-rewriter event handling failed: {exc}")

    def _rewriter_wait_turn_result(self, turn_id: str, timeout_sec: float) -> dict[str, Any] | None:
        if not turn_id:
            return None
        deadline = time.time() + max(0.5, float(timeout_sec))
        while time.time() < deadline:
            self._rewriter_drain_events(max_items=200)
            current = self.rewriter_turn_results.get(turn_id)
            if isinstance(current, dict):
                status = str(current.get("status") or "").strip().lower()
                if status == "completed":
                    self.rewriter_turn_results.pop(turn_id, None)
                    return current
            if not self._rewriter_is_running():
                break
            time.sleep(0.05)
        return None
