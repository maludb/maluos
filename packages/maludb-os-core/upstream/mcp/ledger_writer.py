"""Prompt-ledger rows for model calls made OUTSIDE the agent runner.

Every model call in the product is recorded (CLAUDE.md, "Agent decisions already made"). Agents'
calls go through the runner's ledger proxy, which writes its own rows. The command-bar assistant
calls the provider directly — and until 2026-09-20 recorded nothing: no prompt, no context, no
latency, no cost for the most-used AI in the product, which no later evaluation could recover.

record() writes one prompt_ledger row and its prompt_payloads row in a transaction, as the app's
own database role (app_rw has INSERT; a payload is visible only through the ledger's views).
Telemetry must never break a user's turn: callers wrap it, and a failure is logged, not raised.
"""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal

import db

log = logging.getLogger("ledger_writer")
MILLION = Decimal(1_000_000)
_pool = None
_models: dict[tuple[str, str], dict | None] = {}


def _plain(value):
    """db.make_pool registers a jsonb codec that encodes for us — hand it plain JSON-able data, never a
    string (a string would be stored as a JSON string, not an object)."""
    return json.loads(json.dumps(value, default=str))


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await db.make_pool(db.ENV.get("DB_USER", ""), db.ENV.get("DB_PASSWORD", ""))
    return _pool


async def _model(con, provider: str, provider_model_id: str) -> dict | None:
    """Any active registry row for this provider model: its prices are the provider's, whatever the harness."""
    key = (provider, provider_model_id)
    if key not in _models:
        row = await con.fetchrow("""
            SELECT id, price_input_per_mtok, price_output_per_mtok, price_cache_read_per_mtok,
                   price_cache_write_per_mtok, currency
              FROM model_registry WHERE provider = $1 AND provider_model_id = $2
             ORDER BY (status = 'active') DESC, id LIMIT 1""", provider, provider_model_id)
        _models[key] = dict(row) if row else None
    return _models[key]


async def record(*, acting_member_id: int, harness: str, provider: str, provider_model_id: str, request_id: str,
                 status: str, context: dict, response, usage: dict | None, latency_ms: int,
                 provider_request_id: str | None = None, error_code: str | None = None,
                 error_message: str | None = None, sdk_version: str | None = None) -> int | None:
    u = usage or {}
    tokens = {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
              "cache_read": int(u.get("cache_read_input_tokens") or 0),
              "cache_write": int(u.get("cache_creation_input_tokens") or 0)}
    try:
        pool = await _get_pool()
        async with pool.acquire() as con, con.transaction():
            model = await _model(con, provider, provider_model_id)
            cost = Decimal(0)
            if model:
                cost = ((tokens["input"] * Decimal(str(model["price_input_per_mtok"] or 0))
                         + tokens["output"] * Decimal(str(model["price_output_per_mtok"] or 0))
                         + tokens["cache_read"] * Decimal(str(model["price_cache_read_per_mtok"] or 0))
                         + tokens["cache_write"] * Decimal(str(model["price_cache_write_per_mtok"] or 0)))
                        / MILLION).quantize(Decimal("0.000001"))
            body = json.dumps({"context": context, "response": response}, sort_keys=True, default=str).encode()
            ledger_id = await con.fetchval("""
                INSERT INTO prompt_ledger (acting_member_id, harness, sdk_version, provider, model_id, provider_model_id,
                       request_id, provider_request_id, call_kind, status, error_code, error_message, input_tokens,
                       output_tokens, cache_read_tokens, cache_write_tokens, latency_ms, cost, currency)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'messages',$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) RETURNING id""",
                acting_member_id, harness, sdk_version, provider, model["id"] if model else None, provider_model_id,
                request_id, provider_request_id, status, error_code, (error_message or None) and error_message[:2000],
                tokens["input"], tokens["output"], tokens["cache_read"], tokens["cache_write"], max(0, latency_ms),
                cost, (model or {}).get("currency") or "USD")
            await con.execute("""
                INSERT INTO prompt_payloads (ledger_id, context, response, byte_size, sha256)
                VALUES ($1, $2::jsonb, $3::jsonb, $4, $5)""",
                ledger_id, _plain(context), _plain(response), len(body),
                hashlib.sha256(body).hexdigest())
            return ledger_id
    except Exception as exc:  # noqa: BLE001 - never break the caller's turn
        log.warning("model call was not ledgered: %s", exc)
        return None
