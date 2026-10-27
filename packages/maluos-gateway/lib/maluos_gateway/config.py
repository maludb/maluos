"""Gateway configuration: /etc/maluos/gateway.yaml with defaults, reloaded on change."""
import os

CONFIG = os.environ.get("MALUOS_GATEWAY_CONFIG", "/etc/maluos/gateway.yaml")
DEFAULTS = {
    "socket": "/run/maluos/gateway.sock",
    "tcp": {"enabled": False, "host": "127.0.0.1", "port": 11435},
    "database": "maludb", "tenant": "maluos",
    "pg_host": "/var/run/postgresql", "pg_user": None, "pg_role": None,
    "identities": {},                 # linux user -> principal ref, when not user:<name>
    "vault_socket": "/run/maluos/vault.sock",
    "catalog_reload_s": 10,
    "status_publish_s": 5,
    "request_timeout_s": 600,
    "principal_queue_limit": 20,
    "affinity": {"max_wait_s": 20, "max_backlog": 4},
    "engine_queue": {"enabled": True, "poll_s": 2, "class": "batch", "principal": "service:engine"},
    "state_dir": "/var/lib/maluos-gateway",
    # Operators on the socket besides root: the provisioning state's `operators` (the human accounts firstboot made
    # database superusers) from operators_file, plus these users. G5: the session service reads the node API as the
    # login user for the MaluOS Network and Queue tabs.
    "operators": [],
    "operators_file": "/var/lib/maluos/firstboot/done",
    "episodes": {"enabled": True},
    "health": {"cooldown_s": 60, "probe_s": 10},      # a memory episode per call that carries a task reference (FR-42)
    "alerts": {"hooks_dir": "/etc/maluos/alert-hooks.d", "check_s": 30, "backend_down_s": 300, "backend_down_repeat_s": 3600,
               "usage_anomaly": {"enabled": True, "check_s": 300, "min_calls": 20, "factor": 3}},
    # Sharing this host's GPU with the MaluOS network (Phase 13 G1; the sharing itself is G2): enabled null = the
    # chassis rule (a server shares, a desktop or laptop only when its owner opts in); contribution null = the rule's
    # (always on a server or desktop, idle on a laptop). `maluctl gateway share on|off [--when always|idle]`.
    "share": {"enabled": None, "contribution": None},
    # Phase 13 G2: this node on the network. name null = the hostname; the id is made at first start (state_dir/node-id).
    "node": {"name": None, "result_retention_hours": 72, "max_finished_jobs": 1000},
    "ollama": {"url": "http://127.0.0.1:11434", "keep_alive": "30m", "max_concurrent": 1,
               "keep_warm": [], "pull": [], "install": False, "version": "v0.40.6"},
    # Seeded into the catalogue at provisioning when it is empty (operators edit the tables after).
    "seed": {
        "classes": [
            {"name": "interactive", "priority": 0, "weight": 4, "max_queue": 50, "fallback_wait_s": 20,
             "description": "humans at a terminal, tools in a session"},
            {"name": "agent", "priority": 1, "weight": 2, "max_queue": 200, "fallback_wait_s": 120,
             "description": "autonomous agents"},
            {"name": "batch", "priority": 2, "weight": 1, "max_queue": 1000, "fallback_wait_s": None,
             "description": "engine maintenance, bulk jobs; waits"},
        ],
        "tiers": {
            "fast": {"description": "small, quick", "local": ["llama3.2:3b", "qwen2.5:3b"],
                     "cloud": [["ollama-cloud", "gpt-oss:20b"], ["anthropic", "claude-haiku-4-5"], ["openai", "gpt-5-mini"]]},
            "standard": {"description": "general purpose", "local": ["llama3.1:8b", "qwen2.5:7b"],
                         "cloud": [["ollama-cloud", "gpt-oss:120b"], ["anthropic", "claude-sonnet-4-5"], ["openai", "gpt-5"]]},
            "strong": {"description": "largest the host can hold, then the strongest cloud model", "local": ["qwen2.5:14b", "llama3.1:8b"],
                       "cloud": [["ollama-cloud", "deepseek-v3.1:671b"], ["anthropic", "claude-opus-4-1"], ["openai", "gpt-5"]]},
            "embed": {"description": "embeddings", "local": ["nomic-embed-text", "bge-m3"], "cloud": [["openai", "text-embedding-3-small"]]},
        },
        # Cloud backends are seeded disabled: enable one with `maluctl gateway backend enable NAME`
        # after storing its key in the vault (`sudo maluctl secret add system/anthropic ...`).
        "cloud_backends": [
            {"name": "ollama-cloud", "kind": "ollama_cloud", "endpoint": "https://ollama.com", "secret_ref": "ollama",
             "models": ["gpt-oss:20b", "gpt-oss:120b", "deepseek-v3.1:671b", "qwen3-coder:480b"]},
            {"name": "anthropic", "kind": "anthropic", "endpoint": "https://api.anthropic.com", "secret_ref": "anthropic",
             "models": ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-1"]},
            {"name": "openai", "kind": "openai", "endpoint": "https://api.openai.com", "secret_ref": "openai",
             "models": ["gpt-5-mini", "gpt-5", "text-embedding-3-small"]},
        ],
        # Rough list prices per million tokens (USD) for estimates; operators correct them (maluctl gateway price set).
        "prices": [
            ["anthropic", "claude-haiku-4-5", 1, 5, 0.1], ["anthropic", "claude-sonnet-4-5", 3, 15, 0.3], ["anthropic", "claude-opus-4-1", 15, 75, 1.5],
            ["openai", "gpt-5-mini", 0.25, 2, 0.025], ["openai", "gpt-5", 1.25, 10, 0.125], ["openai", "text-embedding-3-small", 0.02, 0, 0],
            ["ollama-cloud", "*", 0, 0, 0],
        ],
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


class Config:
    def __init__(self, path=CONFIG):
        self.path, self._mtime, self.data = path, None, dict(DEFAULTS)
        self.reload()

    def reload(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self.data = dict(DEFAULTS); return False
        if st.st_mtime == self._mtime:
            return False
        import yaml
        with open(self.path) as f:
            user = yaml.safe_load(f) or {}
        self.data, self._mtime = _merge(DEFAULTS, user), st.st_mtime
        return True

    def __getitem__(self, k):
        self.reload(); return self.data[k]

    def get(self, k, default=None):
        self.reload(); return self.data.get(k, default)
