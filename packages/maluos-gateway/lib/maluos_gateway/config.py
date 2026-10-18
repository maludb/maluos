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
    "engine_queue": {"enabled": True, "poll_s": 2, "class": "batch"},
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
            "fast": {"description": "small, quick", "local": ["llama3.2:3b", "qwen2.5:3b"]},
            "standard": {"description": "general purpose", "local": ["llama3.1:8b", "qwen2.5:7b"]},
            "strong": {"description": "largest the host can hold", "local": ["qwen2.5:14b", "llama3.1:8b"]},
            "embed": {"description": "embeddings", "local": ["nomic-embed-text", "bge-m3"]},
        },
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
