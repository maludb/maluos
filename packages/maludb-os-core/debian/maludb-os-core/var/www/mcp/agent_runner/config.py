"""Runner settings. The runner runs as its own unix user and reads its OWN env file — it cannot
read config/.env, and the provider API keys live only here (the agent never sees one)."""
from __future__ import annotations

import os
from pathlib import Path


def _load(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = {**_load(os.environ.get("RUNNER_ENV_FILE", "/etc/business-os/runner.env")), **os.environ}


def get(key: str, default: str = "") -> str:
    return ENV.get(key, default)


def require(key: str, min_len: int = 1) -> str:
    value = ENV.get(key, "")
    if len(value) < min_len:
        raise RuntimeError(f"{key} is not configured (runner.env).")
    return value


API_PORT = int(get("RUNNER_API_PORT", "8815"))
PROXY_PORT = int(get("RUNNER_PROXY_PORT", "8816"))
AGENTS_DIR = Path(get("RUNNER_AGENTS_DIR", "/var/lib/business-os/agents"))
HERMES_BIN = get("HERMES_BIN", "/opt/hermes/venv/bin/hermes")
CLAUDE_BIN = get("CLAUDE_BIN", "/opt/claude-agent/bin/claude")   # pinned; see mcp/claude_conformance
PHP_BASE = get("PHP_BASE", "http://127.0.0.1:8080")   # the PHP JSON API: localhost-only since the React cut-over; :80 is the React app
MAX_WORKERS = int(get("RUNNER_MAX_WORKERS", "2"))
DEFAULT_RUN_TIMEOUT = int(get("RUNNER_DEFAULT_TIMEOUT", "900"))
AGENT_UNIX_USER = get("RUNNER_AGENT_USER", "")     # empty = run Hermes as the runner's own user (dev only)

# Claude subscription (Max plan) login — the owner's own install only (docs/build-specs/claude-subscription-auth.md).
# OFF unless BOTH the explicit switch and the token are in runner.env. The token never reaches an agent: the ledger
# proxy swaps it in for the run's key on a model whose auth_mode is claude_subscription, as it does an API key.
SUBSCRIPTION_MAX_CONCURRENT = int(get("RUNNER_SUBSCRIPTION_MAX_CONCURRENT", "1"))   # one Max login, one shared limit


def subscription_token() -> str:
    return get("CLAUDE_CODE_OAUTH_TOKEN").strip()


def subscription_enabled() -> bool:
    return get("ALLOW_CLAUDE_SUBSCRIPTION") == "1" and len(subscription_token()) >= 20


# provider -> (env key holding the API key, upstream base URL, wire)
PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com", "anthropic"),
    "openai":    ("OPENAI_API_KEY", "https://api.openai.com", "openai"),
    "deepseek":  ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "openai"),
    "moonshot":  ("MOONSHOT_API_KEY", "https://api.moonshot.ai", "openai"),
    # Fireworks serves many open models behind one OpenAI-compatible API; its /v1 lives under /inference.
    "fireworks": ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference", "openai"),
    # OpenRouter: JEV (TypeSafe's System One model) for eval grading — its own wire, systemone (db/144).
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api", "systemone"),
}
