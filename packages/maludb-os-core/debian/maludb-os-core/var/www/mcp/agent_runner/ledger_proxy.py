"""The ledger proxy: the prompt ledger's only complete source.

Every model slot of every harness is pointed here. H0 proved why it has to be the wire and not
the harness's hooks: Hermes' observer hooks never see auxiliary calls (compression, titling) —
2 of 17 calls in one run. The proxy also holds the provider keys, so the agent tier never does,
and it is where an exhausted budget stops a call before it is made.

  POST /openai/v1/chat/completions     POST /anthropic/v1/messages     GET /{wire}/v1/models[/id]
  anything else -> quiet 404 (Hermes probes /api/show and /api/v1/models before use)

Identity is the KEY ('run.{run}.{exp}.{hmac}'), never a header: Hermes sends no custom header on
auxiliary calls. The request is forwarded byte-for-byte except three things — the model id is
forced to the run's registered model (an agent cannot spend on a model its ledger row would not
name), the auth header becomes the real provider key, and an OpenAI stream is asked to include
usage. Streams are tee'd to the caller unmodified and the row is written when the stream ends or
is cut.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from decimal import Decimal

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import config, pricing, run_token, store

log = logging.getLogger("ledger_proxy")
APP_KEY_PREFIX = "appm_"
ZERO = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
DROP_REQUEST_HEADERS = {"host", "authorization", "x-api-key", "content-length", "accept-encoding", "connection"}
unledgered_runs: set[int] = set()      # runs with a call the ledger could not record; the runner fails them


def _error(wire: str, status: int, kind: str, message: str) -> JSONResponse:
    if wire == "anthropic":
        return JSONResponse({"type": "error", "error": {"type": kind, "message": message}}, status_code=status)
    return JSONResponse({"error": {"type": kind, "code": kind, "message": message}}, status_code=status)


async def _authenticate(request: Request, wire: str):
    presented = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
    secret = config.require("PROXY_KEY_SECRET", 32)
    run_id = run_token.verify_proxy_key(presented, secret)
    if run_id is not None:
        run = await store.run_for_proxy(run_id)
        if run is None or run["status"] != "running":
            return None, _error(wire, 401, "authentication_error", "That run is not running.")
        return run, None
    # A GRADING call, made by the runner while evaluating. It is not an agent's call: it has no
    # agent run behind it, it is pinned to the JUDGE's model rather than the model under test, and
    # it is written to the ledger as call_kind='grader' so judging is never mistaken for work.
    eval_run_id = run_token.verify_judge_key(presented, secret)
    if eval_run_id is not None:
        judge = await store.judge_for_proxy(eval_run_id)
        if judge is None:
            return None, _error(wire, 401, "authentication_error", "That evaluation is not running.")
        return judge, None
    # K24: an APPLICATION's own model call (an engine behind it — MaluDB's extraction, embedding and answers). Its credential
    # is shown once and only its hash is kept (db/171); it is confined to the models it names and an optional monthly cap.
    token = presented.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token.startswith(APP_KEY_PREFIX):
        app = await store.app_credential_for_proxy(hashlib.sha256(token.encode()).hexdigest())
        if app is None:
            return None, _error(wire, 401, "authentication_error", "Unknown, revoked or expired application credential.")
        return app, None
    return None, _error(wire, 401, "authentication_error", "Unknown or expired run key.")


def _pick_model(run: dict, asked) -> dict | None:
    """The registered model an application credential may call: named by the registry key or the provider's id."""
    for m in run.get("allowed_models") or []:
        if asked in (m["provider_model_id"], m["model_key"]):
            return m
    return None


async def _spent(run: dict) -> Decimal:
    if run.get("is_application"):
        return await store.application_month_cost(run["application_id"])
    return await store.month_to_date_cost(run["agent_member_id"])


def _upstream(run: dict, wire: str, path: str | None = None) -> tuple[str, dict]:
    model = run["model"]
    key_env, default_base, _ = config.PROVIDERS.get(model["provider"], ("", "", wire))
    base = (model.get("endpoint_url") or default_base).rstrip("/")
    path = path or ("/v1/messages" if wire == "anthropic" else "/v1/chat/completions")
    if model.get("auth_mode") == "claude_subscription":
        # The owner's Max login: the token replaces the run's key exactly as an API key would. It is the ONLY thing changed;
        # the client's own headers (identity, betas) travel untouched, and the agent never holds the token.
        return base + path, {"authorization": "Bearer " + config.subscription_token()}
    api_key = config.get(key_env) if key_env else ""
    if not api_key:          # a local or keyless endpoint (Ollama, vLLM, the conformance dummy)
        return base + path, {}
    auth = {"x-api-key": api_key} if wire == "anthropic" else {"authorization": f"Bearer {api_key}"}
    return base + path, auth


class _Assembler:
    """Rebuilds the final message and usage from an SSE stream, for the ledger payload."""

    def __init__(self, wire: str):
        self.wire, self.buffer = wire, b""
        self.usage: dict = {}
        self.text: list[str] = []
        self.tools: dict[int, dict] = {}
        self.stop: str | None = None
        self.id: str | None = None

    def feed(self, chunk: bytes) -> None:
        self.buffer += chunk
        while b"\n\n" in self.buffer:
            event, self.buffer = self.buffer.split(b"\n\n", 1)
            for line in event.splitlines():
                if line.startswith(b"data:"):
                    data = line[5:].strip()
                    if data and data != b"[DONE]":
                        try:
                            self._event(json.loads(data))
                        except ValueError:
                            pass

    def _event(self, e: dict) -> None:
        if self.wire == "anthropic":
            kind = e.get("type")
            if kind == "message_start":
                message = e.get("message") or {}
                self.id, self.usage = message.get("id"), dict(message.get("usage") or {})
            elif kind == "content_block_start":
                block = e.get("content_block") or {}
                if block.get("type") == "tool_use":
                    self.tools[e.get("index", 0)] = {"id": block.get("id"), "name": block.get("name"), "arguments": ""}
            elif kind == "content_block_delta":
                delta = e.get("delta") or {}
                if delta.get("type") == "text_delta":
                    self.text.append(delta.get("text", ""))
                elif delta.get("type") == "input_json_delta" and e.get("index", 0) in self.tools:
                    self.tools[e.get("index", 0)]["arguments"] += delta.get("partial_json", "")
            elif kind == "message_delta":
                self.stop = (e.get("delta") or {}).get("stop_reason") or self.stop
                self.usage.update(e.get("usage") or {})
            return
        self.id = e.get("id") or self.id
        if e.get("usage"):
            self.usage = e["usage"]
        for choice in e.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.text.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                slot = self.tools.setdefault(tc.get("index", 0), {"id": None, "name": None, "arguments": ""})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["name"] = fn.get("name") or slot["name"]
                slot["arguments"] += fn.get("arguments") or ""
            self.stop = choice.get("finish_reason") or self.stop

    def message(self) -> dict:
        return {"streamed": True, "id": self.id, "text": "".join(self.text),
                "tool_calls": [self.tools[i] for i in sorted(self.tools)], "stop_reason": self.stop,
                "usage": self.usage}


async def _record(run: dict, wire: str, *, status: str, started: float, context, response, usage=None,
                  provider_request_id=None, error_code=None, error_message=None) -> None:
    tokens = pricing.normalise_usage(wire, usage) if usage else dict(ZERO)
    try:
        await store.write_ledger(run=run, status=status, provider_request_id=provider_request_id, tokens=tokens,
                                 latency_ms=int((time.monotonic() - started) * 1000),
                                 cost=pricing.cost(tokens, run["model"]), context=context, response=response,
                                 error_code=error_code, error_message=error_message,
                                 call_kind=run.get("call_kind") or "messages")
    except Exception:
        if run["id"] is not None:
            unledgered_runs.add(run["id"])          # the runner fails a run whose calls went unrecorded
        log.exception("%s: a model call could NOT be written to the prompt ledger",
                      f"run {run['id']}" if run["id"] is not None else f"eval run {run.get('eval_run_id')}")


def _status_for(code: int) -> str:
    return "ok" if code < 400 else "rate_limited" if code == 429 else "error"


async def _forward(request: Request, wire: str, *, embeddings: bool = False) -> Response:
    run, refusal = await _authenticate(request, wire)
    if refusal is not None:
        return refusal
    if embeddings and not run.get("is_application"):
        return _error(wire, 403, "permission_error", "Embeddings are an application credential's alone.")
    if run.get("model") and run["model"].get("auth_mode") == "claude_subscription" and (
            wire != "anthropic" or run.get("harness") != "claude_agent_sdk" or not config.subscription_enabled()):
        return _error(wire, 403, "permission_error", "Claude subscription use is switched off, or this is not the official Claude Code client on the Anthropic wire.")
    started = time.monotonic()
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _error(wire, 400, "invalid_request_error", "The request body is not JSON.")

    if run.get("is_application"):
        # K24: the caller names the model, but only among those the credential was minted for — a call whose ledger row
        # could not name what it spent on is never made.
        run["model"] = _pick_model(run, body.get("model"))
        if run["model"] is None:
            return _error(wire, 403, "permission_error", "That model is not allowed for this application credential.")
        run["model_id"] = run["model"]["id"]
        run["call_kind"] = "embedding" if embeddings else "messages"
    # Budget, BEFORE forwarding. This read is also the ledger's pre-flight: if the database is
    # down it raises, the call is not forwarded, and nothing goes unrecorded.
    budget = run.get("monthly_budget_amount")
    if budget is not None and await _spent(run) >= budget:
        who = "application" if run.get("is_application") else "agent"
        await _record(run, wire, status="refused", started=started, context=body, response=None,
                      error_code="budget_exhausted", error_message=f"Monthly budget exhausted for this {who}.")
        return _error(wire, 402, "budget_exhausted", f"Monthly budget exhausted for this {who}.")

    body["model"] = run["model"]["provider_model_id"]
    if wire == "openai" and body.get("stream"):
        body.setdefault("stream_options", {})["include_usage"] = True
    url, auth = _upstream(run, wire, "/v1/embeddings" if embeddings else None)
    # A harness may qualify the call with a query string — the Claude Code CLI asks for
    # /v1/messages?beta=true — and dropping it would silently change what was asked for. The path
    # is ours (the route decided the wire); the query is the caller's and travels with it.
    if request.url.query:
        url += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQUEST_HEADERS}
    headers.update(auth)
    headers["accept-encoding"] = "identity"            # the ledger reads the bytes it tees
    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))

    try:
        upstream = await client.send(client.build_request("POST", url, json=body, headers=headers), stream=True)
    except httpx.TimeoutException as exc:
        await client.aclose()
        await _record(run, wire, status="timeout", started=started, context=body, response=None, error_message=str(exc))
        return _error(wire, 504, "timeout", "The model provider timed out.")
    except httpx.HTTPError as exc:
        await client.aclose()
        await _record(run, wire, status="error", started=started, context=body, response=None,
                      error_code="upstream_unreachable", error_message=str(exc))
        return _error(wire, 502, "api_error", "The model provider could not be reached.")

    request_id = upstream.headers.get("request-id") or upstream.headers.get("x-request-id")
    content_type = upstream.headers.get("content-type", "application/json")

    if "text/event-stream" not in content_type:
        payload = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = {"raw": payload.decode("utf-8", "replace")[:4000]}
        failed = upstream.status_code >= 400
        err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
        await _record(run, wire, status=_status_for(upstream.status_code), started=started, context=body,
                      response=parsed, usage=None if failed else parsed.get("usage"), provider_request_id=request_id,
                      error_code=(err.get("type") or err.get("code")) if failed else None,
                      error_message=err.get("message") if failed else None)
        return Response(payload, status_code=upstream.status_code, media_type=content_type)

    assembler = _Assembler(wire)

    async def tee():
        status = "ok"
        try:
            async for chunk in upstream.aiter_raw():
                assembler.feed(chunk)
                yield chunk                                     # unmodified
        except (asyncio.CancelledError, GeneratorExit):
            status = "cancelled"
            raise
        except httpx.HTTPError:
            status = "error"
        finally:
            await upstream.aclose()
            await client.aclose()
            await asyncio.shield(_record(run, wire, status=status, started=started, context=body,
                                         response=assembler.message(), usage=assembler.usage,
                                         provider_request_id=request_id))

    return StreamingResponse(tee(), status_code=upstream.status_code, media_type=content_type)


JEV_MODEL_KEY = "jev:typesafe/jev-1.13"
SYSTEMONE_RETRIES = 3


async def systemone(request: Request) -> Response:
    """A JEV grading call (db/144): OpenRouter's System One API, reached only with an evaluation's
    judge key. The model is pinned to the registered JEV row (never the caller's), the provider is
    asked for zero data retention and no data collection, 429/529 are retried with backoff, and the
    call is ledgered as call_kind 'grader' with OpenRouter's own usage.cost."""
    presented = request.headers.get("authorization") or ""
    secret = config.require("PROXY_KEY_SECRET", 32)
    # A system_one agent's own run (db/145): its key names a running run on the JEV model, and the
    # call counts against that agent's budget like any agent's.
    agent_run_id = run_token.verify_proxy_key(presented, secret)
    if agent_run_id is not None:
        run = await store.run_for_proxy(agent_run_id)
        if run is None or run["status"] != "running" or run["model"].get("harness") != "system_one":
            return JSONResponse({"error": {"message": "Only a running system_one agent, or an evaluation, may call JEV."}},
                                status_code=401)
        run["call_kind"] = "messages"
        budget = run.get("monthly_budget_amount")
        if budget is not None and await store.month_to_date_cost(run["agent_member_id"]) >= budget:
            await _record(run, "systemone", status="refused", started=time.monotonic(), context=None, response=None,
                          error_code="budget_exhausted", error_message="Monthly budget exhausted for this agent.")
            return JSONResponse({"error": {"message": "Monthly budget exhausted for this agent."}}, status_code=402)
    else:
        eval_run_id = run_token.verify_judge_key(presented, secret)
        if eval_run_id is None:
            return JSONResponse({"error": {"message": "Only an evaluation's judge key may call JEV."}}, status_code=401)
        run = await store.judge_for_proxy(eval_run_id, JEV_MODEL_KEY)
        if run is None:
            return JSONResponse({"error": {"message": "That evaluation is not running, or JEV is not registered."}},
                                status_code=401)
    key_env, base, _ = config.PROVIDERS["openrouter"]
    api_key = config.get(key_env)
    started = time.monotonic()
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        return JSONResponse({"error": {"message": "The request body is not JSON."}}, status_code=400)
    if not api_key:
        await _record(run, "systemone", status="refused", started=started, context=body, response=None,
                      error_code="not_configured", error_message="OPENROUTER_API_KEY is not set in runner.env.")
        return JSONResponse({"error": {"message": "JEV is not configured."}}, status_code=503)
    body["model"] = run["model"]["provider_model_id"]
    body["provider"] = {"zdr": True, "data_collection": "deny"}
    url = (run["model"].get("endpoint_url") or (base + "/v1/systemone"))
    upstream = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        for attempt in range(SYSTEMONE_RETRIES):
            try:
                upstream = await client.post(url, json=body, headers={"authorization": f"Bearer {api_key}"})
            except httpx.HTTPError as exc:
                await _record(run, "systemone", status="error", started=started, context=body, response=None,
                              error_code="upstream_unreachable", error_message=str(exc))
                return JSONResponse({"error": {"message": "JEV could not be reached."}}, status_code=502)
            if upstream.status_code not in (429, 529) or attempt == SYSTEMONE_RETRIES - 1:
                break
            await asyncio.sleep(float(upstream.headers.get("retry-after") or 2 ** attempt))
    try:
        parsed = upstream.json()
    except ValueError:
        parsed = {"raw": upstream.text[:4000]}
    failed = upstream.status_code >= 400
    usage = parsed.get("usage") if isinstance(parsed, dict) else None
    tokens = {"input": int((usage or {}).get("input_tokens") or 0), "output": int((usage or {}).get("output_tokens") or 0),
              "cache_read": 0, "cache_write": 0}
    cost = pricing.cost(tokens, run["model"])
    if usage and usage.get("cost") is not None:
        cost = Decimal(str(usage["cost"])).quantize(Decimal("0.000001"))
    err = (parsed.get("error") or {}) if isinstance(parsed, dict) and failed else {}
    try:
        await store.write_ledger(run=run, status=_status_for(upstream.status_code),
                                 provider_request_id=parsed.get("id") if isinstance(parsed, dict) else None,
                                 tokens=tokens, latency_ms=int((time.monotonic() - started) * 1000), cost=cost,
                                 context=body, response=parsed, error_code=(err.get("code") and str(err.get("code"))) or None,
                                 error_message=err.get("message"), call_kind=run.get("call_kind") or "grader")
    except Exception:
        if run.get("id") is not None:
            unledgered_runs.add(run["id"])
        log.exception("a JEV call could NOT be written to the prompt ledger (%s)", run.get("id") or run.get("eval_run_id"))
        return JSONResponse({"error": {"message": "The ledger could not record the JEV call."}}, status_code=500)
    return JSONResponse(parsed, status_code=upstream.status_code)


async def chat_completions(request: Request) -> Response:
    return await _forward(request, "openai")


async def messages(request: Request) -> Response:
    return await _forward(request, "anthropic")


async def embeddings(request: Request) -> Response:
    return await _forward(request, "openai", embeddings=True)


async def models(request: Request) -> Response:
    wire = request.path_params["wire"]
    run, refusal = await _authenticate(request, wire)
    if refusal is not None:
        return refusal
    if run.get("is_application"):      # an application credential may name any of its allowed models
        listed = [{"id": m["provider_model_id"], "object": "model", "type": "model", "display_name": m["display_name"]}
                  for m in run["allowed_models"]]
        wanted = request.path_params.get("model_id")
        if wanted is None:
            return JSONResponse({"object": "list", "data": listed, "has_more": False})
        hit = next((e for e in listed if e["id"] == wanted), None)
        return JSONResponse(hit) if hit else _error(wire, 404, "not_found_error", "No such model.")
    model_id = run["model"]["provider_model_id"]
    entry = {"id": model_id, "object": "model", "type": "model", "display_name": run["model"]["display_name"]}
    wanted = request.path_params.get("model_id")
    if wanted is not None:
        return JSONResponse(entry) if wanted == model_id else _error(wire, 404, "not_found_error", "No such model.")
    return JSONResponse({"object": "list", "data": [entry], "has_more": False})


async def not_found(request: Request) -> Response:
    return JSONResponse({"error": "not found"}, status_code=404)


app = Starlette(routes=[
    Route("/openai/v1/chat/completions", chat_completions, methods=["POST"]),
    Route("/anthropic/v1/messages", messages, methods=["POST"]),
    Route("/openai/v1/embeddings", embeddings, methods=["POST"]),
    Route("/openrouter/api/v1/systemone", systemone, methods=["POST"]),
    Route("/{wire:str}/v1/models", models, methods=["GET"]),
    Route("/{wire:str}/v1/models/{model_id:path}", models, methods=["GET"]),
    Route("/{rest:path}", not_found, methods=["GET", "POST", "HEAD"]),
])
