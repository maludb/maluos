"""Can this registered model do what an agent needs? One tiny question, asked of the provider directly.

    sudo -u bos-runner env RUNNER_ENV_FILE=/etc/business-os/runner.env \\
        /var/www/mcp/venv/bin/python -m agent_runner.probe_model hermes:deepseek-flash [more model keys…]

An agent on the OpenAI wire needs three things from a model: it must CALL A TOOL when one fits,
stream, and report usage at the end of the stream (the ledger's cost comes from it). This sends
one streaming request with one tool and says which of the three held, plus what the call would
have cost at the registry's prices and which usage fields the provider used for cache hits.

An operator's diagnostic, run by hand before an agent is put on a model: it is NOT an agent's
call, goes around the ledger proxy, and writes nothing. It costs a fraction of a cent.
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx

from . import config, pricing, store

TOOL = {"type": "function", "function": {
    "name": "find_invoices", "description": "Find invoices by status.",
    "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["overdue", "paid", "draft"]}},
                   "required": ["status"], "additionalProperties": False}}}
MESSAGES = [{"role": "system", "content": "You are an accounts assistant. Use your tools; never guess figures."},
            {"role": "user", "content": "Which invoices are overdue?"}]


async def probe(model_key: str) -> str:
    p = await store.pool()
    async with p.acquire() as con:
        row = await con.fetchrow("SELECT * FROM model_registry WHERE model_key = $1", model_key)
    if row is None:
        return f"{model_key}: not in the model registry"
    model = dict(row)
    key_env, default_base, wire = config.PROVIDERS.get(model["provider"], ("", "", "openai"))
    if wire != "openai":
        return f"{model_key}: {model['provider']} is not on the OpenAI wire — this probe does not cover it"
    base = (model.get("endpoint_url") or default_base).rstrip("/")
    body = {"model": model["provider_model_id"], "messages": MESSAGES, "tools": [TOOL], "stream": True,
            "stream_options": {"include_usage": True}, "max_tokens": 2000}
    calls, text, usage, chunks = {}, [], None, 0
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", base + "/v1/chat/completions", json=body,
                                     headers={"authorization": f"Bearer {config.get(key_env)}"}) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode(errors="replace")[:200]
                    return f"{model_key}: HTTP {r.status_code} — {detail}"
                async for line in r.aiter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    event = json.loads(line[5:])
                    chunks += 1
                    usage = event.get("usage") or usage
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        text.append(delta.get("content") or "")
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["arguments"] += fn.get("arguments") or ""
    except httpx.HTTPError as exc:
        return f"{model_key}: {type(exc).__name__}: {exc}"

    called = [c for c in calls.values() if c["name"]]
    good_call = False
    for c in called:
        try:
            good_call = c["name"] == "find_invoices" and json.loads(c["arguments"] or "{}").get("status") == "overdue"
        except ValueError:
            pass
    tokens = pricing.normalise_usage("openai", usage)
    cache_fields = sorted(k for k in ((usage or {}).get("prompt_tokens_details") or {}) if "cach" in k) + \
        sorted(k for k in (usage or {}) if "cache" in k)
    verdict = "OK" if good_call and usage else "NOT FIT FOR AN AGENT"
    return (f"{model_key}: {verdict} — tool call: {'yes, correct arguments' if good_call else ('yes, wrong' if called else 'NO')}; "
            f"streamed {chunks} chunks; usage: {'yes' if usage else 'NO'} {tokens if usage else ''}; "
            f"cost {pricing.cost(tokens, model) if usage else '?'}; cache fields: {cache_fields or 'none reported'}"
            + (f"; said instead: {''.join(text)[:80]!r}" if not called else ""))


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for line in await asyncio.gather(*(probe(k) for k in sys.argv[1:])):
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
