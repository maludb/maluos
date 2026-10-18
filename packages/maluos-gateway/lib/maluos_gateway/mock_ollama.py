"""A mock Ollama server for tests: the native API with deterministic replies,
per-token delays, token counts, concurrency and order tracking. Shipped so the
image boot test can exercise the real gateway without a GPU.

  python3 -m maluos_gateway.mock_ollama --port 11999 [--token-delay 0.01] [--models mock-7b,mock-13b,mock-embed]
"""
import argparse, asyncio, hashlib, json, time
from aiohttp import web

STATE = {"running": 0, "max_running": 0, "order": [], "aborted": 0, "warm": 0, "calls": 0, "loaded": {}, "models": {}, "token_delay": 0.01,
         "keys": [], "cloud_calls": 0}


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def model_entry(name):
    return {"name": name if ":" in name else name + ":latest", "model": name if ":" in name else name + ":latest", "modified_at": now_iso(),
            "size": 4_000_000_000, "digest": hashlib.sha256(name.encode()).hexdigest(), "details": {"family": "mock", "parameter_size": "7B"}}


def resolve(name):
    if name in STATE["models"]:
        return name
    if name and name.endswith(":latest") and name[:-7] in STATE["models"]:
        return name[:-7]
    if name and (name + ":latest") in STATE["models"]:
        return name + ":latest"
    return None


async def gen_tokens(model, text, options, kind, n_prompt):
    """Yield (chunk_dict, is_final)."""
    toks = text.split(" ")
    total = float(options.get("mock_delay_s", 0) or 0)
    per = (total / max(1, len(toks))) if total else STATE["token_delay"]
    t0 = time.monotonic()
    loaded_before = model in STATE["loaded"]
    load_ns = 0 if loaded_before else 300_000_000
    if not loaded_before:
        await asyncio.sleep(0.3)
    STATE["loaded"][model] = time.time() + 300
    for i, tok in enumerate(toks):
        await asyncio.sleep(per)
        piece = tok + (" " if i < len(toks) - 1 else "")
        yield ({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": piece}, "done": False}
               if kind == "chat" else {"model": model, "created_at": now_iso(), "response": piece, "done": False}), False
    dur = int((time.monotonic() - t0) * 1e9)
    final = {"model": model, "created_at": now_iso(), "done": True, "done_reason": "stop", "total_duration": dur, "load_duration": load_ns,
             "prompt_eval_count": n_prompt, "prompt_eval_duration": 50_000_000, "eval_count": len(toks), "eval_duration": max(1, dur - load_ns - 50_000_000)}
    if kind == "chat":
        final["message"] = {"role": "assistant", "content": ""}
    else:
        final["response"] = ""
    yield final, True


async def run_generation(request, kind):
    body = await request.json()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        STATE["keys"].append({"provider": "ollama", "key": auth[7:], "model": body.get("model")})
    model = resolve(body.get("model"))
    if not model:
        return web.json_response({"error": f"model '{body.get('model')}' not found, try pulling it first"}, status=404)
    if model.startswith("mock-fail"):
        STATE["calls"] += 1
        return web.json_response({"error": "mock failure: the local runner crashed"}, status=500)
    options = body.get("options") or {}
    if kind == "chat":
        msgs = body.get("messages") or []
        prompt = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
        if isinstance(prompt, list):
            prompt = " ".join(p.get("text", "") for p in prompt if p.get("type") == "text")
    else:
        prompt = body.get("prompt") or ""
    n_prompt = len(prompt.split()) + 3
    if prompt == "" and not body.get("messages"):
        STATE["warm"] += 1
        STATE["loaded"][model] = time.time() + 300
        return web.json_response({"model": model, "created_at": now_iso(), "response": "", "done": True, "done_reason": "load"})
    tag = options.get("tag") or ""
    reply = f"mock reply to: {prompt[:60]}"
    if options.get("mock_words"):
        reply = " ".join(f"w{i}" for i in range(int(options["mock_words"])))
    tool_calls = None
    if kind == "chat" and body.get("tools") and "call tool" in prompt.lower():
        fn = (body["tools"][0].get("function") or {}).get("name", "tool")
        tool_calls = [{"function": {"name": fn, "arguments": {"x": 1}}}]
    stream = body.get("stream", True)
    STATE["calls"] += 1
    STATE["running"] += 1
    STATE["max_running"] = max(STATE["max_running"], STATE["running"])
    entry = {"model": model, "tag": tag, "kind": kind, "start": time.time(), "end": None, "prompt": prompt[:40]}
    STATE["order"].append(entry)
    try:
        if not stream:
            final, parts = None, []
            async for chunk, is_final in gen_tokens(model, reply, options, kind, n_prompt):
                if is_final:
                    final = chunk
                else:
                    parts.append(chunk["message"]["content"] if kind == "chat" else chunk["response"])
            if kind == "chat":
                final["message"] = {"role": "assistant", "content": "".join(parts)}
                if tool_calls:
                    final["message"]["tool_calls"] = tool_calls
            else:
                final["response"] = "".join(parts)
            if body.get("format") == "json" or isinstance(body.get("format"), dict):
                if kind == "chat":
                    final["message"]["content"] = json.dumps({"reply": final["message"]["content"]})
                else:
                    final["response"] = json.dumps({"reply": final["response"]})
            return web.json_response(final)
        resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await resp.prepare(request)
        async for chunk, is_final in gen_tokens(model, reply, options, kind, n_prompt):
            if is_final and tool_calls:
                chunk["message"]["tool_calls"] = tool_calls
            await resp.write((json.dumps(chunk) + "\n").encode())
        await resp.write_eof()
        return resp
    except (asyncio.CancelledError, ConnectionResetError):
        STATE["aborted"] += 1
        raise
    finally:
        STATE["running"] -= 1
        entry["end"] = time.time()


async def h_chat(request):
    return await run_generation(request, "chat")


async def h_generate(request):
    return await run_generation(request, "generate")


async def h_embed(request):
    body = await request.json()
    model = resolve(body.get("model"))
    if not model:
        return web.json_response({"error": f"model '{body.get('model')}' not found"}, status=404)
    inp = body.get("input", body.get("prompt", ""))
    items = inp if isinstance(inp, list) else [inp]
    STATE["calls"] += 1
    STATE["order"].append({"model": model, "tag": (body.get("options") or {}).get("tag", ""), "kind": "embed", "start": time.time(), "end": time.time(), "prompt": str(items[0])[:40]})
    embs = []
    for s in items:
        h = hashlib.sha256(str(s).encode()).digest()
        embs.append([round((b - 128) / 128.0, 4) for b in h[:8]])
    await asyncio.sleep(0.02)
    return web.json_response({"model": model, "embeddings": embs, "total_duration": 20_000_000, "load_duration": 0,
                              "prompt_eval_count": sum(len(str(s).split()) for s in items)})


async def h_embeddings_legacy(request):
    body = await request.json()
    r = await h_embed(request.clone())
    return r


async def h_tags(request):
    return web.json_response({"models": [model_entry(m) for m in STATE["models"]]})


async def h_ps(request):
    now = time.time()
    STATE["loaded"] = {m: exp for m, exp in STATE["loaded"].items() if exp > now}
    return web.json_response({"models": [{"name": m if ":" in m else m + ":latest", "model": m, "size": 4_000_000_000, "size_vram": 4_000_000_000,
                                          "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))} for m, exp in STATE["loaded"].items()]})


async def h_version(request):
    return web.json_response({"version": "0.0.0-mock"})


async def h_show(request):
    body = await request.json()
    model = resolve(body.get("model") or body.get("name"))
    if not model:
        return web.json_response({"error": "model not found"}, status=404)
    return web.json_response({"modelfile": f"FROM {model}", "details": {"family": "mock"}, "model_info": {"general.architecture": "mock"}})


async def h_pull(request):
    body = await request.json()
    name = body.get("model") or body.get("name")
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await resp.prepare(request)
    for st in ({"status": "pulling manifest"}, {"status": "downloading", "total": 100, "completed": 50}, {"status": "success"}):
        await resp.write((json.dumps(st) + "\n").encode()); await asyncio.sleep(0.05)
    STATE["models"][name] = True
    await resp.write_eof()
    return resp


# ---- cloud emulation: Anthropic Messages and OpenAI Chat Completions (keys are recorded, never checked for value)
def _last_user(msgs):
    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            return c or ""
    return ""


async def h_anthropic_messages(request):
    key = request.headers.get("x-api-key")
    if not key:
        return web.json_response({"type": "error", "error": {"type": "authentication_error", "message": "x-api-key required"}}, status=401)
    body = await request.json()
    STATE["keys"].append({"provider": "anthropic", "key": key, "model": body.get("model")}); STATE["cloud_calls"] += 1
    if body.get("model") == "claude-fail":
        return web.json_response({"type": "error", "error": {"type": "overloaded_error", "message": "mock overloaded"}}, status=529)
    prompt = _last_user(body.get("messages") or [])
    text = f"mock claude reply to: {prompt[:60]}"
    tool_use = None
    if body.get("tools") and "call tool" in prompt.lower():
        tool_use = {"type": "tool_use", "id": "toolu_mock1", "name": body["tools"][0]["name"], "input": {"x": 1}}
    n_in, n_out = len(prompt.split()) + 5, len(text.split())
    if not body.get("stream"):
        content = [{"type": "text", "text": text}] + ([tool_use] if tool_use else [])
        return web.json_response({"id": "msg_mock", "type": "message", "role": "assistant", "model": body.get("model"), "content": content,
                                  "stop_reason": "tool_use" if tool_use else "end_turn", "usage": {"input_tokens": n_in, "output_tokens": n_out, "cache_read_input_tokens": 2}},
                                 headers={"request-id": "req_mock_anthropic"})
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "request-id": "req_mock_anthropic"})
    await resp.prepare(request)
    async def ev(name, obj):
        await resp.write(f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode())
    await ev("message_start", {"type": "message_start", "message": {"id": "msg_mock", "type": "message", "role": "assistant", "content": [], "model": body.get("model"),
                                                                   "usage": {"input_tokens": n_in, "output_tokens": 1, "cache_read_input_tokens": 2}}})
    await ev("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    for i, tok in enumerate(text.split(" ")):
        await asyncio.sleep(STATE["token_delay"])
        await ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": tok + (" " if i < n_out - 1 else "")}})
    await ev("content_block_stop", {"type": "content_block_stop", "index": 0})
    if tool_use:
        await ev("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_mock1", "name": tool_use["name"], "input": {}}})
        await ev("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"x": 1}'}})
        await ev("content_block_stop", {"type": "content_block_stop", "index": 1})
    await ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use" if tool_use else "end_turn", "stop_sequence": None}, "usage": {"output_tokens": n_out}})
    await ev("message_stop", {"type": "message_stop"})
    await resp.write_eof()
    return resp


async def h_openai_chat(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": {"message": "bearer token required", "type": "invalid_request_error"}}, status=401)
    key = auth[7:]
    body = await request.json()
    STATE["keys"].append({"provider": "openai", "key": key, "model": body.get("model")}); STATE["cloud_calls"] += 1
    prompt = _last_user(body.get("messages") or [])
    text = f"mock gpt reply to: {prompt[:60]}"
    n_in, n_out = len(prompt.split()) + 4, len(text.split())
    tool_calls = None
    if body.get("tools") and "call tool" in prompt.lower():
        tool_calls = [{"id": "call_mock1", "type": "function", "function": {"name": body["tools"][0]["function"]["name"], "arguments": '{"x": 1}'}}]
    usage = {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out, "prompt_tokens_details": {"cached_tokens": 3}}
    if not body.get("stream"):
        msg = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return web.json_response({"id": "chatcmpl-mock", "object": "chat.completion", "model": body.get("model"),
                                  "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}], "usage": usage},
                                 headers={"x-request-id": "req_mock_openai"})
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "x-request-id": "req_mock_openai"})
    await resp.prepare(request)
    async def chunk(delta, fin=None, extra=None):
        obj = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "model": body.get("model"), "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
        obj.update(extra or {})
        await resp.write(f"data: {json.dumps(obj)}\n\n".encode())
    await chunk({"role": "assistant", "content": ""})
    for i, tok in enumerate(text.split(" ")):
        await asyncio.sleep(STATE["token_delay"])
        await chunk({"content": tok + (" " if i < n_out - 1 else "")})
    if tool_calls:
        await chunk({"tool_calls": [{"index": 0, "id": "call_mock1", "type": "function", "function": {"name": tool_calls[0]["function"]["name"], "arguments": ""}}]})
        await chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"x": 1}'}}]})
    await chunk({}, "tool_calls" if tool_calls else "stop")
    await resp.write(f"data: {json.dumps({'id': 'chatcmpl-mock', 'object': 'chat.completion.chunk', 'model': body.get('model'), 'choices': [], 'usage': usage})}\n\n".encode())
    await resp.write(b"data: [DONE]\n\n")
    await resp.write_eof()
    return resp


async def h_openai_embeddings(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": {"message": "bearer token required"}}, status=401)
    body = await request.json()
    STATE["keys"].append({"provider": "openai", "key": auth[7:], "model": body.get("model")}); STATE["cloud_calls"] += 1
    inp = body.get("input"); items = inp if isinstance(inp, list) else [inp]
    data = [{"object": "embedding", "index": i, "embedding": [round((b - 128) / 128.0, 4) for b in hashlib.sha256(str(s).encode()).digest()[:8]]} for i, s in enumerate(items)]
    return web.json_response({"object": "list", "data": data, "model": body.get("model"), "usage": {"prompt_tokens": sum(len(str(s).split()) for s in items), "total_tokens": 0}})


async def h_root(request):
    return web.Response(text="mock\n")


async def h_stats(request):
    return web.json_response({k: v for k, v in STATE.items() if k != "models"} | {"models": list(STATE["models"])})


async def h_reset(request):
    STATE.update({"running": 0, "max_running": 0, "order": [], "aborted": 0, "warm": 0, "calls": 0, "loaded": {}, "keys": [], "cloud_calls": 0})
    return web.json_response({"reset": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=11999)
    ap.add_argument("--token-delay", type=float, default=0.01); ap.add_argument("--models", default="mock-7b,mock-13b,mock-embed")
    a = ap.parse_args()
    STATE["token_delay"] = a.token_delay
    STATE["models"] = {m: True for m in a.models.split(",") if m}
    app = web.Application()
    app.router.add_post("/api/chat", h_chat); app.router.add_post("/api/generate", h_generate)
    app.router.add_post("/api/embed", h_embed); app.router.add_post("/api/embeddings", h_embed)
    app.router.add_get("/api/tags", h_tags); app.router.add_get("/api/ps", h_ps); app.router.add_get("/api/version", h_version)
    app.router.add_post("/api/show", h_show); app.router.add_post("/api/pull", h_pull)
    app.router.add_get("/mock/stats", h_stats); app.router.add_post("/mock/reset", h_reset)
    app.router.add_post("/v1/messages", h_anthropic_messages); app.router.add_post("/v1/chat/completions", h_openai_chat)
    app.router.add_post("/v1/embeddings", h_openai_embeddings); app.router.add_get("/", h_root)
    web.run_app(app, host=a.host, port=a.port, print=None, access_log=None, handler_cancellation=True)


if __name__ == "__main__":
    main()
