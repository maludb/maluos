"""How the Claude Code CLI is launched for a run — one place, shared by the harness and the conformance suite
(mcp/claude_conformance) so the fences the suite proves are the fences the runner uses.

Two modes, chosen by the agent's model row (model_registry.auth_mode, db/164):

  api_key             `--bare`: an API key is the ONLY way the CLI can authenticate, and hooks, plugin sync, memory,
                      CLAUDE.md discovery and keychain reads are all off. The key in the environment is the run's proxy key.

  claude_subscription the owner's Max login (docs/build-specs/claude-subscription-auth.md). `--bare` cannot use a
                      subscription, so the CLI runs whole and is FENCED explicitly instead. The token in the environment is
                      still only the run's proxy key — the ledger proxy swaps the real token in — but presented as a
                      claude.ai login so the CLI builds its own request as it does for one. Whatever `--bare` used to
                      switch off is switched off here by flag, by environment and by the empty per-agent HOME, config dir
                      and cwd; the conformance suite plants a hook, CLAUDE.md files, settings, agents, skills and an extra
                      MCP server in every place the CLI looks and fails if any of them takes effect.
"""
from __future__ import annotations

SUBSCRIPTION = "claude_subscription"

# What --bare is documented to switch off, switched off by name. The suite proves the set; add to it, never remove.
SUBSCRIPTION_ENV = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",          # no memory directory read or written
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",           # no CLAUDE.md discovery (user, project, parents)
    "CLAUDE_CODE_DISABLE_ORG_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_POLICY_SKILLS": "1",
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", # nothing but the model call leaves the box
    "CLAUDE_CODE_DISABLE_ATTRIBUTION_CROSS_REPO": "1",
}
# Load NO setting source (user, project, local): the only settings are the --settings file the runner renders.
SUBSCRIPTION_FLAGS = ["--setting-sources", "", "--no-session-persistence"]


def is_subscription(model: dict) -> bool:
    return (model or {}).get("auth_mode") == SUBSCRIPTION


def auth_env(model: dict, proxy_key: str, proxy_url: str) -> dict[str, str]:
    """The environment that points the CLI at the ledger proxy and gives it its (proxy) credential."""
    if is_subscription(model):
        return {"ANTHROPIC_BASE_URL": proxy_url, "CLAUDE_CODE_OAUTH_TOKEN": proxy_key, **SUBSCRIPTION_ENV}
    return {"ANTHROPIC_BASE_URL": proxy_url, "ANTHROPIC_API_KEY": proxy_key}


def fence_flags(model: dict) -> list[str]:
    """The flags that (with the environment) stand in for the isolation of `--bare`."""
    return SUBSCRIPTION_FLAGS[:] if is_subscription(model) else ["--bare"]
