"""Cloud adapters: Anthropic Messages and OpenAI Chat Completions, behind the
same interface as the Ollama adapter. The gateway's canonical request is the
Ollama-native chat body (messages with role/content/images/tool_calls, tools
in OpenAI function form, options, format); adapters translate it and yield
canonical chunks ({"message": {...}, "done": bool, counts}), so the server's
OpenAI and Ollama output translators work unchanged for every backend."""
import asyncio, json, secrets, time
import aiohttp

from .ollama import OllamaBackend, BackendError, _ollama_error


def _options(body):
    o = body.get("options") or {}
    return {"temperature": o.get("temperature"), "top_p": o.get("top_p"), "max_tokens": o.get("num_predict"),
            "stop": o.get("stop"), "seed": o.get("seed")}


def _generate_to_messages(body):
    msgs = []
    if body.get("system"):
        msgs.append({"role": "system", "content": body["system"]})
    m = {"role": "user", "content": body.get("prompt") or ""}
    if body.get("images"):
        m["images"] = body["images"]
    msgs.append(m)
    return msgs


def _image_block(b64):
    head = b64[:8]
    media = "image/png" if head.startswith("iVBOR") else "image/gif" if head.startswith("R0lGOD") else "image/webp" if head.startswith("UklGR") else "image/jpeg"
    return media


def _final(model, text, tool_calls, done_reason, tokens_in, tokens_out, cached, t0, load_s=0.0, kind="chat", request_id=None):
    total = time.monotonic() - t0
    out = {"model": model, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "done": True, "done_reason": done_reason,
           "total_duration": int(total * 1e9), "load_duration": int(load_s * 1e9), "prompt_eval_count": tokens_in,
           "prompt_eval_duration": 0, "eval_count": tokens_out, "eval_duration": int(total * 1e9), "cached_tokens": cached,
           "provider_request_id": request_id}
    if kind == "chat":
        out["message"] = {"role": "assistant", "content": text}
        if tool_calls:
            out["message"]["tool_calls"] = tool_calls
    else:
        out["response"] = text
    return out


class CloudBackend(OllamaBackend):
    """Shared plumbing: canonical paths map to chat/embed; generate becomes chat."""
    is_cloud = True

    async def stream(self, path, body, timeout_s=600, key=None):
        kind = "generate" if path == "/api/generate" else "chat"
        if path == "/api/embed":
            yield await self.embed(body, timeout_s, key); return
        msgs = _generate_to_messages(body) if kind == "generate" else body.get("messages") or []
        async for chunk in self.chat_stream(body, msgs, kind, timeout_s, key):
            yield chunk

    async def call(self, path, body, timeout_s=600, key=None):
        if path == "/api/embed":
            return await self.embed(body, timeout_s, key)
        final, parts, tool_calls = None, [], []
        async for chunk in self.stream(path, body, timeout_s, key):
            if chunk.get("done"):
                final = chunk
            else:
                msg = chunk.get("message") or {}
                parts.append(msg.get("content") or chunk.get("response") or "")
                tool_calls += msg.get("tool_calls") or []
        if final is None:
            raise BackendError(502, f"{self.name}: stream ended without a final message")
        text = "".join(parts)
        if "message" in final:
            final["message"]["content"] = text
            if tool_calls and not final["message"].get("tool_calls"):
                final["message"]["tool_calls"] = tool_calls
        else:
            final["response"] = text
        return final

    async def embed(self, body, timeout_s, key):
        raise BackendError(400, f"{self.name} ({self.kind}) has no embeddings", "capability")

    async def _post(self, path, payload, headers, timeout_s, stream):
        try:
            r = await self.session.post(self.endpoint + path, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=None if stream else timeout_s, sock_connect=10, sock_read=timeout_s))
        except aiohttp.ClientConnectorError as e:
            self.fail()
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")
        except asyncio.TimeoutError:
            raise BackendError(504, f"{self.name} timed out", "timeout")
        if r.status >= 400:
            text = (await r.text())[:400]
            r.release()
            cls = {401: "bad_credential", 403: "bad_credential", 404: "model_not_found", 429: "rate_limited"}.get(r.status, "backend_error")
            if r.status >= 500:
                self.fail(30)
            raise BackendError(r.status if r.status in (401, 403, 404, 429) else 502, f"{self.name}: {_ollama_error(text)}", cls)
        return r


async def _sse(resp):
    """Yield (event, data) from a text/event-stream response."""
    event, data = None, []
    async for raw in resp.content:
        line = raw.decode(errors="replace").rstrip("\r\n")
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if data:
        yield event, "\n".join(data)


class AnthropicBackend(CloudBackend):
    VERSION = "2023-06-01"

    def headers(self, key=None):
        h = {"anthropic-version": self.VERSION, "Content-Type": "application/json"}
        if key:
            h["x-api-key"] = key
        return h

    def to_request(self, body, msgs, model):
        system, out = [], []
        for m in msgs:
            role, content = m.get("role"), m.get("content") or ""
            if role in ("system", "developer"):
                system.append(content); continue
            if role == "tool":
                out.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "toolu_unknown", "content": content}]})
                continue
            blocks = []
            for img in m.get("images") or []:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": _image_block(img), "data": img}})
            if content:
                blocks.append({"type": "text", "text": content})
            if role == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    blocks.append({"type": "tool_use", "id": tc.get("id") or f"toolu_{secrets.token_hex(8)}", "name": fn.get("name"), "input": fn.get("arguments") or {}})
            if not blocks:
                blocks = [{"type": "text", "text": " "}]
            if out and out[-1]["role"] == role == "user":
                out[-1]["content"] += blocks
            else:
                out.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})
        o = _options(body)
        req = {"model": model, "messages": out, "max_tokens": int(o["max_tokens"] or self.options.get("max_tokens") or 4096)}
        if body.get("format"):
            system.append("Respond with a single JSON object and nothing else." + (f" It must match this JSON schema: {json.dumps(body['format'])}" if isinstance(body["format"], dict) else ""))
        if system:
            req["system"] = "\n\n".join(system)
        for k in ("temperature", "top_p"):
            if o[k] is not None:
                req[k] = o[k]
        if o["stop"]:
            req["stop_sequences"] = list(o["stop"])
        if body.get("tools"):
            req["tools"] = [{"name": (t.get("function") or {}).get("name"), "description": (t.get("function") or {}).get("description") or "",
                             "input_schema": (t.get("function") or {}).get("parameters") or {"type": "object", "properties": {}}} for t in body["tools"]]
        return req

    async def chat_stream(self, body, msgs, kind, timeout_s, key):
        if not key:
            raise BackendError(401, f"{self.name}: no credential", "no_credential")
        model = body["model"]
        req = dict(self.to_request(body, msgs, model), stream=True)
        t0 = time.monotonic()
        r = await self._post("/v1/messages", req, self.headers(key), timeout_s, True)
        rid = r.headers.get("request-id")
        tokens_in = tokens_out = cached = 0
        stop = None
        blocks = {}
        tool_calls = []
        try:
            async for event, data in _sse(r):
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "message_start":
                    u = (obj.get("message") or {}).get("usage") or {}
                    tokens_in, cached = u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0) or 0
                elif t == "content_block_start":
                    cb = obj.get("content_block") or {}
                    blocks[obj.get("index")] = {"type": cb.get("type"), "id": cb.get("id"), "name": cb.get("name"), "json": ""}
                elif t == "content_block_delta":
                    d = obj.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield {"model": model, "created_at": "", "done": False,
                               **({"message": {"role": "assistant", "content": d["text"]}} if kind == "chat" else {"response": d["text"]})}
                    elif d.get("type") == "input_json_delta":
                        blocks[obj.get("index")]["json"] += d.get("partial_json", "")
                elif t == "content_block_stop":
                    b = blocks.get(obj.get("index")) or {}
                    if b.get("type") == "tool_use":
                        try:
                            args = json.loads(b["json"] or "{}")
                        except json.JSONDecodeError:
                            args = {"_raw": b["json"]}
                        tc = {"id": b.get("id"), "function": {"name": b.get("name"), "arguments": args}}
                        tool_calls.append(tc)
                        if kind == "chat":
                            yield {"model": model, "created_at": "", "done": False, "message": {"role": "assistant", "content": "", "tool_calls": [tc]}}
                elif t == "message_delta":
                    stop = (obj.get("delta") or {}).get("stop_reason") or stop
                    tokens_out = (obj.get("usage") or {}).get("output_tokens", tokens_out)
                elif t == "error":
                    raise BackendError(502, f"{self.name}: {(obj.get('error') or {}).get('message', 'stream error')}")
        finally:
            r.release()
        reason = {"end_turn": "stop", "max_tokens": "length", "tool_use": "stop", "stop_sequence": "stop"}.get(stop, "stop")
        yield _final(model, "", None, reason, tokens_in, tokens_out, cached, t0, kind=kind, request_id=rid)


class OpenAIBackend(CloudBackend):
    def headers(self, key=None):
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def to_request(self, body, msgs, model):
        out = []
        for m in msgs:
            role, content = m.get("role"), m.get("content") or ""
            om = {"role": "system" if role == "developer" else role}
            if m.get("images"):
                om["content"] = [{"type": "text", "text": content}] + [{"type": "image_url", "image_url": {"url": f"data:{_image_block(i)};base64,{i}"}} for i in m["images"]]
            else:
                om["content"] = content
            if role == "assistant" and m.get("tool_calls"):
                om["tool_calls"] = [{"id": tc.get("id") or f"call_{secrets.token_hex(8)}", "type": "function",
                                     "function": {"name": (tc.get("function") or {}).get("name"), "arguments": json.dumps((tc.get("function") or {}).get("arguments") or {})}}
                                    for tc in m["tool_calls"]]
                if not content:
                    om["content"] = None
            if role == "tool":
                om["tool_call_id"] = m.get("tool_call_id") or "call_unknown"
            out.append(om)
        o = _options(body)
        req = {"model": model, "messages": out}
        for k, dst in (("temperature", "temperature"), ("top_p", "top_p"), ("seed", "seed")):
            if o[k] is not None:
                req[dst] = o[k]
        if o["max_tokens"]:
            req["max_completion_tokens"] = int(o["max_tokens"])
        if o["stop"]:
            req["stop"] = list(o["stop"])
        if body.get("tools"):
            req["tools"] = body["tools"]
        fmt = body.get("format")
        if fmt == "json":
            req["response_format"] = {"type": "json_object"}
        elif isinstance(fmt, dict):
            req["response_format"] = {"type": "json_schema", "json_schema": {"name": "response", "schema": fmt}}
        return req

    async def chat_stream(self, body, msgs, kind, timeout_s, key):
        if not key:
            raise BackendError(401, f"{self.name}: no credential", "no_credential")
        model = body["model"]
        req = dict(self.to_request(body, msgs, model), stream=True, stream_options={"include_usage": True})
        t0 = time.monotonic()
        r = await self._post("/v1/chat/completions", req, self.headers(key), timeout_s, True)
        rid = r.headers.get("x-request-id")
        tokens_in = tokens_out = cached = 0
        finish = None
        pending = {}
        tool_calls = []
        try:
            async for event, data in _sse(r):
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    raise BackendError(502, f"{self.name}: {(obj['error'] or {}).get('message', 'stream error')}")
                u = obj.get("usage")
                if u:
                    tokens_in, tokens_out = u.get("prompt_tokens", tokens_in), u.get("completion_tokens", tokens_out)
                    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or cached
                for ch in obj.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        yield {"model": model, "created_at": "", "done": False,
                               **({"message": {"role": "assistant", "content": d["content"]}} if kind == "chat" else {"response": d["content"]})}
                    for tc in d.get("tool_calls") or []:
                        p = pending.setdefault(tc.get("index", 0), {"id": tc.get("id"), "name": "", "args": ""})
                        fn = tc.get("function") or {}
                        p["id"] = p["id"] or tc.get("id"); p["name"] += fn.get("name") or ""; p["args"] += fn.get("arguments") or ""
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
        finally:
            r.release()
        for i in sorted(pending):
            p = pending[i]
            try:
                args = json.loads(p["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": p["args"]}
            tool_calls.append({"id": p["id"], "function": {"name": p["name"], "arguments": args}})
        if tool_calls and kind == "chat":
            yield {"model": model, "created_at": "", "done": False, "message": {"role": "assistant", "content": "", "tool_calls": tool_calls}}
        reason = {"stop": "stop", "length": "length", "tool_calls": "stop", "content_filter": "stop"}.get(finish, "stop")
        yield _final(model, "", None, reason, tokens_in, tokens_out, cached, t0, kind=kind, request_id=rid)

    async def embed(self, body, timeout_s, key):
        if not key:
            raise BackendError(401, f"{self.name}: no credential", "no_credential")
        inp = body.get("input")
        req = {"model": body["model"], "input": inp}
        t0 = time.monotonic()
        r = await self._post("/v1/embeddings", req, self.headers(key), timeout_s, False)
        try:
            obj = await r.json()
        finally:
            r.release()
        data = sorted(obj.get("data") or [], key=lambda d: d.get("index", 0))
        n = (obj.get("usage") or {}).get("prompt_tokens", 0)
        return {"model": body["model"], "embeddings": [d.get("embedding") for d in data], "prompt_eval_count": n,
                "total_duration": int((time.monotonic() - t0) * 1e9), "load_duration": 0, "provider_request_id": r.headers.get("x-request-id")}


class OllamaCloudBackend(OllamaBackend):
    """Ollama cloud: the native API with a bearer token; models are declared in options.models."""
    is_cloud = True

    async def stream(self, path, body, timeout_s=600, key=None):
        if not key:
            raise BackendError(401, f"{self.name}: no credential", "no_credential")
        async for obj in super().stream(path, body, timeout_s, key):
            yield obj

    async def call(self, path, body, timeout_s=600, key=None):
        if not key:
            raise BackendError(401, f"{self.name}: no credential", "no_credential")
        return await super().call(path, body, timeout_s, key)


def make_backend(row, session):
    kind = row["kind"]
    cls = {"anthropic": AnthropicBackend, "openai": OpenAIBackend, "openai_compat": OpenAIBackend, "ollama_cloud": OllamaCloudBackend}.get(kind, OllamaBackend)
    return cls(row, session)
