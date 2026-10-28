"""The two credentials a run is given — and the only two.

  run token   '{member}.{exp}.{run}.{hmac}' over "run:member.exp.run", keyed on ACTION_TOKEN_KEY.
              The Bearer for records/activity MCP and the action token for the actions MCP.
              Verified by mcp/db.py and app/auth.php; PHP honours it only when the actions server
              relays it, so the agent cannot POST to a handler itself.
  proxy key   'run.{run}.{exp}.{hmac}' keyed on PROXY_KEY_SECRET. It IS the run's identity at the
              ledger proxy: Hermes sends no custom header on auxiliary calls (H0), so nothing
              else could say which run a model call belongs to.

  judge key   'eval.{eval_run}.{exp}.{hmac}' keyed on PROXY_KEY_SECRET. The identity of the model
              that GRADES an evaluation: it pins the judge's own model at the proxy (a run key
              would pin the agent's, which is the model under test) and attributes the call to the
              eval run. It is held only by the runner — never by an agent — and buys nothing but
              the right to make a graded call.

The first two live as long as the run and exist only in the agent process's environment.
"""
from __future__ import annotations

import hashlib
import hmac
import time


def mint_run_token(member_id: int, run_id: int, ttl_seconds: int, key: str) -> str:
    if len(key) < 32:
        raise RuntimeError("ACTION_TOKEN_KEY is not configured.")
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(key.encode(), f"run:{member_id}.{exp}.{run_id}".encode(), hashlib.sha256).hexdigest()
    return f"{member_id}.{exp}.{run_id}.{sig}"


def mint_proxy_key(run_id: int, ttl_seconds: int, secret: str) -> str:
    if len(secret) < 32:
        raise RuntimeError("PROXY_KEY_SECRET is not configured.")
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(secret.encode(), f"proxy:{run_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"run.{run_id}.{exp}.{sig}"


def verify_proxy_key(presented: str, secret: str) -> int | None:
    """The agent_runs id a proxy key names, or None. Accepts a bare key or 'Bearer <key>'."""
    key = presented.strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    parts = key.split(".")
    if len(parts) != 4 or parts[0] != "run" or not (parts[1].isdigit() and parts[2].isdigit()) or len(secret) < 32:
        return None
    expected = hmac.new(secret.encode(), f"proxy:{parts[1]}.{parts[2]}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[3]) or time.time() > int(parts[2]):
        return None
    return int(parts[1])


def mint_judge_key(eval_run_id: int, ttl_seconds: int, secret: str) -> str:
    if len(secret) < 32:
        raise RuntimeError("PROXY_KEY_SECRET is not configured.")
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(secret.encode(), f"judge:{eval_run_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"eval.{eval_run_id}.{exp}.{sig}"


def verify_judge_key(presented: str, secret: str) -> int | None:
    """The eval_runs id a judge key names, or None. Deliberately a DIFFERENT prefix and payload
    from a proxy key, so neither can ever be accepted where the other is meant."""
    key = presented.strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    parts = key.split(".")
    if len(parts) != 4 or parts[0] != "eval" or not (parts[1].isdigit() and parts[2].isdigit()) or len(secret) < 32:
        return None
    expected = hmac.new(secret.encode(), f"judge:{parts[1]}.{parts[2]}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[3]) or time.time() > int(parts[2]):
        return None
    return int(parts[1])
