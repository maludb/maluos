"""
LLM helper layer — embeddings, chunking, extraction, and provider-agnostic completions.

Ports PHP's config/llm.php + the mem_vector_literal / mem_resolve_token glue from
config/response.php.  PostgreSQL cannot make outbound HTTP calls, so the API is the
model worker: it calls the LLM (extraction: text -> JSON) and the embedding model,
then writes the results back via the maludb_* facades.

Functions:
    mem_embed_dim          — configured embedding dimension (default 1536)
    mem_embed_deterministic — sha256-seeded unit vector (no live creds needed)
    mem_embed              — real HTTP embedding if configured, else deterministic
    mem_embed_http         — POST to OpenAI-shape /embeddings endpoint
    mem_chunk              — split text by paragraph/sentence boundaries with overlap
    llm_complete           — provider-agnostic dispatch (openai | anthropic)
    llm_complete_openai    — POST to /v1/chat/completions
    llm_complete_anthropic — POST to /v1/messages (top-level system)
    llm_json_from_text     — tolerant JSON extraction from LLM output
    mem_extract            — extract SVPO edges via LLM
    mem_vector_literal     — format float list as SQL-castable "[0.1,-0.2,...]"
    mem_resolve_token      — resolve secret via DB or env fallback

Uses httpx for HTTP calls (sync client).  Handles errors gracefully.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any

import httpx

from app import config
from app.errors import json_error

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def mem_embed_dim() -> int:
    """Return the embedding dimension from config (default 1536)."""
    d = config.EMBED_DIM
    return d if d > 0 else 1536


def mem_embed_deterministic(text: str) -> list[float]:
    """Repeatable sha256-seeded unit vector.  Same text -> same vector.

    Generates mem_embed_dim() floats in [-1,1] from successive sha256 blocks
    seeded by ``text + ':' + block_index``, then L2-normalizes to a unit vector.
    """
    dim = mem_embed_dim()
    vec: list[float] = []
    block_idx = 0
    sq_sum = 0.0
    while len(vec) < dim:
        block = hashlib.sha256(f"{text}:{block_idx}".encode()).digest()
        for byte_val in block:
            if len(vec) >= dim:
                break
            v = (byte_val - 127.5) / 127.5
            vec.append(v)
            sq_sum += v * v
        block_idx += 1
    norm = math.sqrt(sq_sum) or 1.0
    return [v / norm for v in vec]


def mem_embed(text: str, cfg: dict | None = None) -> list[float]:
    """Embed text.  If a real embedding endpoint is configured (cfg or env), call it;
    otherwise return a deterministic unit vector derived from the text.
    """
    if cfg is None:
        cfg = {}
    base = cfg.get("embedding_base_url") or os.environ.get("MALUDB_EMBED_BASE_URL", "")
    tok = cfg.get("embedding_token") or os.environ.get("MALUDB_EMBED_TOKEN", "")
    model = cfg.get("embedding_model") or os.environ.get("MALUDB_EMBED_MODEL", "")
    if base and tok and model:
        return mem_embed_http(text, base, tok, model)
    return mem_embed_deterministic(text)


def mem_embed_http(text: str, base_url: str, token: str, model: str) -> list[float]:
    """POST to an OpenAI-shape embeddings endpoint and return the vector."""
    url = base_url.rstrip("/") + "/embeddings"
    timeout = int(os.environ.get("MALUDB_HTTP_TIMEOUT", "60"))
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"input": text, "model": model},
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
    except httpx.HTTPError as exc:
        json_error("upstream_error", f"Model HTTP call failed: {exc}", 502)

    if resp.status_code >= 400:
        json_error("upstream_error", f"Model endpoint returned HTTP {resp.status_code}.", 502)

    data = resp.json()
    emb = None
    if isinstance(data, dict) and isinstance(data.get("data"), list) and data["data"]:
        emb = data["data"][0].get("embedding")
    if not isinstance(emb, list):
        json_error("upstream_error", "Embedding provider returned no vector.", 502)
    return [float(v) for v in emb]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def mem_chunk(text: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
    """Split text into chunks of ~max_chars with overlap, preferring paragraph/sentence
    boundaries.  Verbatim text is preserved in each chunk.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    total = len(text)
    pos = 0
    while pos < total:
        end = pos + max_chars
        slic = text[pos:end]
        if end < total:
            # Try to cut at a paragraph, sentence, or word boundary.
            cut = -1
            for sep in ("\n\n", ". ", " "):
                idx = slic.rfind(sep)
                if idx > max_chars * 0.5:
                    cut = idx
                    break
            if cut > max_chars * 0.5:
                slic = slic[: cut + 1]
        slic = slic.strip()
        if slic:
            chunks.append(slic)
        advance = max(1, len(slic) - overlap)
        pos += advance
    return chunks


# ---------------------------------------------------------------------------
# LLM completions — provider-agnostic dispatch
# ---------------------------------------------------------------------------


def llm_complete(cfg: dict, system: str, user: str) -> str:
    """Provider-agnostic system+user completion.  Dispatched by cfg['api_format']."""
    fmt = str(cfg.get("api_format", "openai")).lower()
    if fmt == "anthropic":
        return llm_complete_anthropic(cfg, system, user)
    return llm_complete_openai(cfg, system, user)


def llm_complete_usage(cfg: dict, system: str, user: str) -> tuple[str, dict]:
    """llm_complete that also answers the provider's usage (M2: a caller can report what a call cost in tokens)."""
    fmt = str(cfg.get("api_format", "openai")).lower()
    if fmt == "anthropic":
        return llm_complete_anthropic_usage(cfg, system, user)
    return llm_complete_openai_usage(cfg, system, user)


def llm_complete_openai(cfg: dict, system: str, user: str) -> str:
    """OpenAI chat/completions with a system + user message."""
    return llm_complete_openai_usage(cfg, system, user)[0]


def llm_complete_openai_usage(cfg: dict, system: str, user: str) -> tuple[str, dict]:
    """The same call, answering (text, usage) — usage is {input_tokens, output_tokens} as the provider reported them."""
    base = cfg.get("base_url", "")
    token = cfg.get("token")
    model = cfg.get("model_identifier", "")
    if not base or token is None or token == "" or not model:
        json_error("model_not_configured", "OpenAI base_url/api_key/model not configured.", 409)

    gen: dict[str, Any] = cfg.get("generation_params") if isinstance(cfg.get("generation_params"), dict) else {}
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        **gen,
    }

    timeout = int(os.environ.get("MALUDB_HTTP_TIMEOUT", "60"))
    url = base.rstrip("/") + "/chat/completions"
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
    except httpx.HTTPError as exc:
        json_error("upstream_error", f"Model HTTP call failed: {exc}", 502)

    if resp.status_code >= 400:
        json_error("upstream_error", f"Model endpoint returned HTTP {resp.status_code}.", 502)

    data = resp.json()
    content = None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        pass
    if not isinstance(content, str):
        json_error("upstream_error", "OpenAI returned no content.", 502)
    u = data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {}
    return content, {
        "input_tokens": int(u.get("prompt_tokens") or 0),
        "output_tokens": int(u.get("completion_tokens") or 0),
    }


def llm_complete_anthropic(cfg: dict, system: str, user: str) -> str:
    """Anthropic messages API — system is a top-level field."""
    return llm_complete_anthropic_usage(cfg, system, user)[0]


def llm_complete_anthropic_usage(cfg: dict, system: str, user: str) -> tuple[str, dict]:
    """The same call, answering (text, usage)."""
    base = cfg.get("base_url", "")
    token = cfg.get("token")
    model = cfg.get("model_identifier", "")
    if not base or token is None or token == "" or not model:
        json_error("model_not_configured", "Anthropic base_url/api_key/model not configured.", 409)

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": int(cfg.get("max_tokens", 2048)),
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    gen = cfg.get("generation_params")
    if isinstance(gen, dict):
        body.update(gen)

    timeout = int(os.environ.get("MALUDB_HTTP_TIMEOUT", "60"))
    url = base.rstrip("/") + "/v1/messages"
    try:
        resp = httpx.post(
            url,
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
    except httpx.HTTPError as exc:
        json_error("upstream_error", f"Model HTTP call failed: {exc}", 502)

    if resp.status_code >= 400:
        json_error("upstream_error", f"Model endpoint returned HTTP {resp.status_code}.", 502)

    data = resp.json()
    # Anthropic: content is an array of blocks; concatenate the text blocks.
    text_out = ""
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
            text_out += block["text"]
    if not text_out:
        json_error("upstream_error", "Anthropic returned no text content.", 502)
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return text_out, {
        "input_tokens": int(u.get("input_tokens") or 0),
        "output_tokens": int(u.get("output_tokens") or 0),
    }


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------


def llm_json_from_text(content: str) -> dict | None:
    """Tolerant JSON extraction from an LLM response.

    Tries: straight decode, fenced ```json block, first {...} span.
    Returns the decoded dict, or None if nothing parses.
    """
    # 1. Straight decode
    try:
        result = json.loads(content.strip())
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Fenced block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(1))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. First {...} span
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(content[start : end + 1])
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


# ---------------------------------------------------------------------------
# Extraction — SVPO edges via LLM
# ---------------------------------------------------------------------------


_DEFAULT_PROMPT = (
    "Extract Subject-Verb-Predicate-Object edges from the text. Use SMALL canonical verbs "
    '(e.g. "upgrade", not "performed_upgrade"); put status/timing/role/detail into the '
    "predicate array as edge-attributes (value_text / value_timestamp / value_numeric). "
    "Prefer subject_type in person|software|project|other. Return ONLY JSON of the form "
    '{"candidate_edges":[{"subject_text":"","subject_type":"","verb_text":"",'
    '"predicate":[{"attr_name":"","value_text":""}],"source_span":"","confidence":0.0}]}.'
    "\n\nText:\n{{chunk}}"
)


def mem_extract(chunk: str, cfg: dict) -> list:
    """Extract SVPO candidate edges from a chunk via the configured LLM.

    Dispatches by ``cfg['api_format']`` (openai | anthropic) so the documents
    path can use a connection borrowed from either model store.  Returns the
    candidate_edges array.  Callers without creds should supply pre-extracted
    edges instead of calling this.
    """
    tmpl = cfg.get("prompt_template") or _DEFAULT_PROMPT
    prompt = tmpl.replace("{{chunk}}", chunk).replace("{{text}}", chunk)

    # Single-user-message completion (no system prompt — the contract lives in the
    # template).  llm_complete validates base_url/token/model and raises
    # model_not_configured if the connection is incomplete.
    content = llm_complete(cfg, "", prompt)

    parsed = llm_json_from_text(content)
    if not isinstance(parsed, dict):
        json_error("upstream_error", "LLM output was not valid JSON.", 502)

    edges = parsed.get("candidate_edges")
    if not isinstance(edges, list):
        json_error("upstream_error", "LLM output was not the candidate_edges contract.", 502)

    return edges


# ---------------------------------------------------------------------------
# SQL / DB helpers
# ---------------------------------------------------------------------------


def mem_vector_literal(floats: list[float]) -> str:
    """Format a float list as a malu_vector SQL literal: ``[0.1,-0.2,...]``.

    Uses fixed-precision, locale-independent formatting (no trailing zeros).
    """

    def _fmt(f: float) -> str:
        s = f"{float(f):.8f}".rstrip("0").rstrip(".")
        return s or "0"

    return "[" + ",".join(_fmt(v) for v in floats) + "]"


def mem_resolve_token(conn, secret_ref: str | None) -> str | None:
    """Resolve a stored secret to its plaintext via maludb_core.__secret_resolve;
    fall back to the MALUDB_LLM_TOKEN env var.

    ``conn`` is the tenant Postgres connection (psycopg.Connection).
    """
    if secret_ref:
        try:
            from app.database import db_one, db_tx_core

            def _resolve(c):
                return db_one(c, "SELECT maludb_core.__secret_resolve(%s) AS tok", [secret_ref])

            row = db_tx_core(conn, _resolve)
            if row and row.get("tok"):
                return str(row["tok"])
        except Exception:
            pass  # No grant or secret missing -> fall through to env.
    return config.LLM_TOKEN
