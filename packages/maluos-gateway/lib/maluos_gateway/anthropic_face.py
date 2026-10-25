"""The Anthropic Messages face (Phase 13 G2, docs/inference-node-api.md §5):
POST /v1/messages in, the message object or the event stream out, errors
in Anthropic's shape. Translates to and from the gateway's canonical
Ollama-native chat body, so every backend serves it unchanged."""
import json, secrets

ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error", 404: "not_found_error",
               409: "invalid_request_error", 429: "rate_limit_error", 503: "overloaded_error"}
STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def error_body(status, code, message):
    return {"type": "error", "error": {"type": ERROR_TYPES.get(status, "api_error"), "message": message, "code": code}}


def _text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text")


def to_ollama(body):
    """The canonical chat body from a Messages request; (body, refused) where refused names an unsupported field."""
    for k in ("thinking",):
        if body.get(k) is not None:
            return None, f"{k} is not supported by this node"
    msgs = []
    if body.get("system"):
        msgs.append({"role": "system", "content": _text_of(body["system"])})
    for m in body.get("messages") or []:
        role, content = m.get("role", "user"), m.get("content")
        if isinstance(content, str):
            msgs.append({"role": role, "content": content}); continue
        text, images, tool_calls, results = [], [], [], []
        for b in content or []:
            t = b.get("type")
            if t == "text":
                text.append(b.get("text", ""))
            elif t == "image":
                src = b.get("source") or {}
                if src.get("type") == "base64" and src.get("data"):
                    images.append(src["data"])
            elif t == "tool_use":
                tool_calls.append({"id": b.get("id") or f"toolu_{secrets.token_hex(8)}", "function": {"name": b.get("name"), "arguments": b.get("input") or {}}})
            elif t == "tool_result":
                results.append({"role": "tool", "content": _text_of(b.get("content")), "tool_call_id": b.get("tool_use_id")})
        om = {"role": role, "content": "\n".join(text)}
        if images:
            om["images"] = images
        if tool_calls:
            om["tool_calls"] = tool_calls
        if text or images or tool_calls or not results:
            msgs.append(om)
        msgs.extend(results)
    opts = {}
    if body.get("max_tokens") is not None:
        opts["num_predict"] = int(body["max_tokens"])
    for k in ("temperature", "top_p", "top_k"):
        if body.get(k) is not None:
            opts[k] = body[k]
    if body.get("stop_sequences"):
        opts["stop"] = list(body["stop_sequences"])
    out = {"messages": msgs}
    if opts:
        out["options"] = opts
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {"name": t.get("name"), "description": t.get("description") or "",
                                                           "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}} for t in body["tools"]]
    return out, None


def content_blocks(msg):
    blocks = []
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"_raw": args}
        blocks.append({"type": "tool_use", "id": tc.get("id") or f"toolu_{secrets.token_hex(8)}", "name": fn.get("name"), "input": args or {}})
    return blocks


def usage(res):
    return {"input_tokens": res.get("prompt_eval_count") or 0, "output_tokens": res.get("eval_count") or 0}


def message(res, model, msg_id, finish):
    msg = res.get("message") or {}
    return {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": content_blocks(msg) or [{"type": "text", "text": ""}],
            "stop_reason": STOP.get(finish, "end_turn"), "stop_sequence": None, "usage": usage(res)}


def ev(name, obj):
    return f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode()


class Stream:
    """SSE event builders for the gateway's streaming loop: on_chunk, on_end, on_error."""

    def __init__(self, model, msg_id, finish_of):
        self.model, self.msg_id, self.finish_of = model, msg_id, finish_of
        self.started, self.index, self.text_open = False, -1, False

    def start(self):
        self.started = True
        return [ev("message_start", {"type": "message_start", "message": {"id": self.msg_id, "type": "message", "role": "assistant", "model": self.model,
                                                                            "content": [], "stop_reason": None, "stop_sequence": None,
                                                                            "usage": {"input_tokens": 0, "output_tokens": 0}}})]

    def close_text(self):
        if not self.text_open:
            return []
        self.text_open = False
        return [ev("content_block_stop", {"type": "content_block_stop", "index": self.index})]

    def on_chunk(self, obj):
        out = [] if self.started else self.start()
        msg = obj.get("message") or {}
        if msg.get("content"):
            if not self.text_open:
                self.index += 1; self.text_open = True
                out.append(ev("content_block_start", {"type": "content_block_start", "index": self.index, "content_block": {"type": "text", "text": ""}}))
            out.append(ev("content_block_delta", {"type": "content_block_delta", "index": self.index, "delta": {"type": "text_delta", "text": msg["content"]}}))
        for b in content_blocks({"tool_calls": msg.get("tool_calls") or []}):
            out += self.close_text()
            self.index += 1
            out.append(ev("content_block_start", {"type": "content_block_start", "index": self.index, "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}}))
            out.append(ev("content_block_delta", {"type": "content_block_delta", "index": self.index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}))
            out.append(ev("content_block_stop", {"type": "content_block_stop", "index": self.index}))
        return out

    def on_end(self, final):
        out = [] if self.started else self.start()
        out += self.close_text()
        u = usage(final or {})
        out.append(ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": STOP.get(self.finish_of(final or {}), "end_turn"), "stop_sequence": None},
                                        "usage": {"input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"]}}))
        out.append(ev("message_stop", {"type": "message_stop"}))
        return out

    def on_error(self, e):
        out = [] if self.started else self.start()
        out += self.close_text()
        out.append(ev("error", error_body(e.status, e.error_class, e.message)))
        return out
