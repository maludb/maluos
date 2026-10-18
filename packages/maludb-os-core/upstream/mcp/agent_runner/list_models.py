"""What does a provider offer right now? Asked of the provider itself, with the key the runner holds.

    sudo -u bos-runner env RUNNER_ENV_FILE=/etc/business-os/runner.env \\
        /var/www/mcp/venv/bin/python -m agent_runner.list_models fireworks [filter]

Prints one line per model: the id to put in the registry's "provider model id", the context
length and whether the provider says it supports tools — an agent needs tool calling, so a model
without it is not a candidate however good it is. Prices are NOT in any provider's listing: take
them from the provider's pricing page when registering the model. Never prints the key.
"""
from __future__ import annotations

import sys

import httpx

from . import config


def fetch(provider: str) -> list[dict]:
    if provider not in config.PROVIDERS:
        raise SystemExit(f"Unknown provider. Known: {', '.join(sorted(config.PROVIDERS))}")
    key_env, base, wire = config.PROVIDERS[provider]
    key = config.get(key_env)
    if not key:
        raise SystemExit(f"{key_env} is not set in the runner's environment (docs/deploy/set-provider-key.sh).")
    headers = ({"x-api-key": key, "anthropic-version": "2023-06-01"} if wire == "anthropic"
               else {"authorization": f"Bearer {key}"})
    out, url, params = [], base.rstrip("/") + "/v1/models", {}
    for _ in range(20):                                   # providers page differently; stop when they stop
        r = httpx.get(url, headers=headers, params=params, timeout=30.0)
        if r.status_code != 200:
            raise SystemExit(f"{provider} answered HTTP {r.status_code} to its model listing.")
        body = r.json()
        out += body.get("data") or body.get("models") or []
        if body.get("has_more") and body.get("last_id"):
            params = {"after_id": body["last_id"]}
        else:
            break
    return out


def describe(m: dict) -> str:
    ctx = m.get("context_length") or m.get("max_input_tokens") or m.get("context_window") or ""
    tools = m.get("supports_tools")
    tools = "tools" if tools is True else "NO tools" if tools is False else "tools?"
    kind = m.get("kind") or m.get("type") or ""
    chat = "" if m.get("supports_chat", True) else " (not a chat model)"
    return f"{m.get('id', '?'):<72} {str(ctx):>9}  {tools:<8} {kind}{chat}"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    needle = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    models = [m for m in fetch(sys.argv[1]) if needle in str(m.get("id", "")).lower()]
    for m in sorted(models, key=lambda m: str(m.get("id"))):
        print(describe(m))
    print(f"{len(models)} model(s).")


if __name__ == "__main__":
    main()
