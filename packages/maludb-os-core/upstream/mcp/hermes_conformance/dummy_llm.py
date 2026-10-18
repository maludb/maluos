"""Scripted OpenAI-compatible endpoint for the Hermes conformance suite. No real model, no cost.

Every Hermes model slot is pointed at its own path prefix — /slot/<name>/v1 — so the log says
which slot made each call. That is the whole point: the prompt ledger will be a proxy in this
position, and any slot that never shows up here is a model call the ledger would miss.

The reply is decided by the request alone, so a run is deterministic:

  * the user message may carry directives  CALL:<tool>:<json-args>  (several, in order).
    While a directive is still unanswered and a tool whose name ends with <tool> is on offer,
    the reply is that tool call. Hermes prefixes MCP tools, hence "ends with".
  * otherwise the reply is plain text: DONE for an agent turn, aux-ok for a call with no tools.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PATH = os.environ.get("KIT_LLM_LOG", "llm.jsonl")
MARKERS = [m for m in os.environ.get("KIT_MARKERS", "").split(",") if m]
_lock = threading.Lock()


def _log(row: dict) -> None:
    with _lock, open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _tool_names(body: dict) -> list[str]:
    """OpenAI nests the name under "function"; Anthropic carries it at the top of the tool."""
    return [(t.get("function") or {}).get("name") or t.get("name") or "" for t in body.get("tools") or []]


def _blocks(message: dict, kind: str) -> int:
    content = message.get("content")
    return sum(1 for b in content if isinstance(b, dict) and b.get("type") == kind) if isinstance(content, list) else 0


def _last_tool_result(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "tool":
            return _text(m.get("content"))
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    return _text(b.get("content"))
    return ""


def _system(body: dict) -> str:
    if "system" in body:  # Anthropic: top-level
        return _text(body["system"])
    return next((_text(m.get("content")) for m in body.get("messages") or [] if m.get("role") == "system"), "")


def _directives(text: str) -> list[tuple[str, str]]:
    """CALL:<tool>:<json> — the JSON is parsed properly, so it may hold spaces, braces, newlines."""
    found, pos, decoder = [], 0, json.JSONDecoder()
    while (start := text.find("CALL:", pos)) != -1:
        colon = text.find(":", start + 5)
        if colon == -1:
            break
        name = text[start + 5:colon].strip()
        try:
            obj, end = decoder.raw_decode(text, colon + 1)
        except ValueError:
            pos = colon + 1
            continue
        found.append((name, json.dumps(obj)))
        pos = end
    return found


def _decide(body: dict) -> dict:
    """Return {'tool': (name, args)} or {'text': str}."""
    messages = body.get("messages") or []
    tools = _tool_names(body)
    if not tools:
        return {"text": "aux-ok"}
    # Only the FIRST user message scripts the run; later user-role text (recalled memory,
    # injected notices) must never be read as a directive.
    user_text = next((_text(m.get("content")) for m in messages if m.get("role") == "user"), "")
    directives = _directives(user_text)
    answered = sum(len(m.get("tool_calls") or []) + _blocks(m, "tool_use")
                   for m in messages if m.get("role") == "assistant")
    if answered < len(directives):
        want, raw_args = directives[answered]
        match = next((t for t in tools if t == want or t.endswith(want)), None)
        if match:
            return {"tool": (match, raw_args)}
        return {"text": f"DONE tool-not-offered:{want}"}
    return {"text": "DONE " + _last_tool_result(messages)[:300]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def _slot(self) -> str:
        m = re.match(r"^/slot/([^/]+)/", self.path)
        return m.group(1) if m else "?"

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        _log({"t": time.time(), "slot": self._slot(), "method": "GET", "path": self.path})
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": "spike-model", "object": "model"}]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        messages = body.get("messages") or []
        system = _system(body)
        # The Claude Code CLI asks for /v1/messages?beta=true, so the wire is decided on the PATH
        # alone — a query string is not part of it (found by the Claude harness spike, 2026-09-20).
        route = self.path.split("?", 1)[0].rstrip("/")
        is_chat = route.endswith("/chat/completions")
        is_anthropic = route.endswith("/messages")
        decision = _decide(body) if (is_chat or is_anthropic) else {"text": "unsupported"}
        refused = self._slot().startswith("refuse")
        _log({
            "t": time.time(), "slot": self._slot(), "method": "POST", "path": self.path,
            "wire": "anthropic" if is_anthropic else "openai" if is_chat else "other",
            "model": body.get("model"), "stream": bool(body.get("stream")),
            "n_messages": len(messages), "n_tools": len(body.get("tools") or []),
            "tool_names": _tool_names(body),
            "last_role": messages[-1].get("role") if messages else None,
            "auth": self.headers.get("Authorization", "") or self.headers.get("x-api-key", ""),
            "x_headers": {k: v for k, v in self.headers.items() if k.lower().startswith("x-bos")},
            "system_chars": len(system), "system_text": system,
            "markers": {m: (m.encode() in raw) for m in MARKERS},
            "marker_roles": {m: sorted({msg.get("role") for msg in messages
                                        if m in _text(msg.get("content"))}) for m in MARKERS},
            "request_bytes": len(raw),
            "decision": "refused" if refused else "tool" if "tool" in decision else decision["text"][:60],
        })
        if refused:  # what the ledger proxy answers when the agent's monthly budget is spent
            return self._json(402, {"error": {"type": "budget_exhausted", "code": "budget_exhausted",
                                              "message": "Monthly budget exhausted for this agent."}})
        if is_anthropic:
            return self._anthropic(body, decision, len(raw))
        if not is_chat:
            return self._json(404, {"error": {"message": "only chat/completions and messages are scripted"}})

        created, cid = int(time.time()), "chatcmpl-spike"
        usage = {"prompt_tokens": max(1, len(raw) // 4), "completion_tokens": 7,
                 "total_tokens": max(1, len(raw) // 4) + 7}
        if "tool" in decision:
            name, args = decision["tool"]
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"call_{int(time.time() * 1000)}", "type": "function",
                 "function": {"name": name, "arguments": args}}]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": decision["text"]}
            finish = "stop"

        if not body.get("stream"):
            return self._json(200, {"id": cid, "object": "chat.completion", "created": created,
                                    "model": body.get("model"), "usage": usage,
                                    "choices": [{"index": 0, "message": message, "finish_reason": finish}]})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def chunk(delta: dict, finish_reason=None, extra=None):
            payload = {"id": cid, "object": "chat.completion.chunk", "created": created,
                       "model": body.get("model"),
                       "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
            if extra:
                payload.update(extra)
            self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n")
            self.wfile.flush()

        chunk({"role": "assistant"})
        if "tool" in decision:
            tc = message["tool_calls"][0]
            chunk({"tool_calls": [{"index": 0, "id": tc["id"], "type": "function",
                                   "function": {"name": tc["function"]["name"], "arguments": ""}}]})
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": tc["function"]["arguments"]}}]})
        else:
            chunk({"content": message["content"]})
        chunk({}, finish_reason=finish)
        if (body.get("stream_options") or {}).get("include_usage"):
            self.wfile.write(b"data: " + json.dumps(
                {"id": cid, "object": "chat.completion.chunk", "created": created,
                 "model": body.get("model"), "choices": [], "usage": usage}).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _anthropic(self, body: dict, decision: dict, request_bytes: int) -> None:
        """Anthropic Messages wire format — the transport Claude models will actually use, so the
        ledger proxy must carry it natively (prompt caching and tool_use blocks do not survive a
        translation to chat-completions)."""
        usage = {"input_tokens": max(1, request_bytes // 4), "output_tokens": 7,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        if "tool" in decision:
            name, args = decision["tool"]
            block = {"type": "tool_use", "id": f"toolu_{int(time.time() * 1000)}", "name": name,
                     "input": json.loads(args)}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": decision["text"]}
            stop = "end_turn"
        base = {"id": "msg_spike", "type": "message", "role": "assistant", "model": body.get("model"),
                "stop_sequence": None}
        if not body.get("stream"):
            return self._json(200, {**base, "content": [block], "stop_reason": stop, "usage": usage})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def event(name: str, payload: dict):
            self.wfile.write(f"event: {name}\n".encode() + b"data: " + json.dumps(payload).encode() + b"\n\n")
            self.wfile.flush()

        event("message_start", {"type": "message_start", "message": {
            **base, "content": [], "stop_reason": None, "usage": {**usage, "output_tokens": 0}}})
        if block["type"] == "tool_use":
            event("content_block_start", {"type": "content_block_start", "index": 0,
                                          "content_block": {**block, "input": {}}})
            event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                          "delta": {"type": "input_json_delta",
                                                    "partial_json": json.dumps(block["input"])}})
        else:
            event("content_block_start", {"type": "content_block_start", "index": 0,
                                          "content_block": {"type": "text", "text": ""}})
            event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                          "delta": {"type": "text_delta", "text": block["text"]}})
        event("content_block_stop", {"type": "content_block_stop", "index": 0})
        event("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                "usage": {"output_tokens": 7}})
        event("message_stop", {"type": "message_stop"})
        self.close_connection = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
