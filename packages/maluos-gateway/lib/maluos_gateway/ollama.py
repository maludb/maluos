"""Ollama backend adapter (local Ollama now; Ollama cloud in slice 3 differs only
in endpoint and credential). Speaks the native API so token counts and
durations are always present; the server translates OpenAI calls to it."""
import asyncio, json, time
import aiohttp


class BackendError(Exception):
    def __init__(self, status, message, error_class="backend_error"):
        super().__init__(message); self.status, self.message, self.error_class = status, message, error_class


class OllamaBackend:
    def __init__(self, row, session):
        self.name, self.kind, self.endpoint = row["name"], row["kind"], row["endpoint"].rstrip("/")
        self.secret_ref = row.get("secret_ref")
        self.options = row.get("options") or {}
        self.capacity = row.get("capacity") or {}
        self.enabled = row.get("enabled", True)
        self.session = session
        self.healthy, self.last_error, self.checked_at = None, None, None
        self.cooldown_until = 0
        self.models, self.loaded, self.version = {}, [], None
        self.system_key = None   # set by the gateway when a system credential exists (for health probes)

    def update(self, row):
        self.endpoint = row["endpoint"].rstrip("/")
        self.secret_ref = row.get("secret_ref")
        self.options, self.capacity, self.enabled = row.get("options") or {}, row.get("capacity") or {}, row.get("enabled", True)

    @property
    def max_concurrent(self):
        return int(self.capacity.get("max_concurrent") or 1)

    def headers(self, key=None):
        return {"Authorization": f"Bearer {key}"} if key else {}

    @property
    def is_cloud(self):
        return self.kind != "ollama_local" and self.kind != "mock"

    cooldown_s = 60   # set from the gateway's health.cooldown_s

    def fail(self, seconds=None):
        """Mark unhealthy for a cool-down after a connection-level failure (FR-32)."""
        self.healthy, self.checked_at = False, time.time()
        self.cooldown_until = time.time() + (seconds if seconds is not None else self.cooldown_s)

    async def refresh(self):
        if time.time() < self.cooldown_until:
            return False
        if self.is_cloud and not self.system_key:
            # No credential to list models with: declared models only; reachability is enough.
            try:
                async with self.session.get(self.endpoint + "/", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    pass
                self.healthy, self.last_error = True, None
            except Exception as e:
                self.healthy, self.last_error = False, f"{e.__class__.__name__}: {str(e)[:120]}"
            self.models = {m: {"name": m, "model": m} for m in (self.options.get("models") or [])}
            self.checked_at = time.time()
            return self.healthy
        try:
            async with self.session.get(self.endpoint + "/api/tags", headers=self.headers(self.system_key), timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    raise BackendError(r.status, (await r.text())[:200])
                tags = await r.json()
            self.models = {m["name"]: m for m in tags.get("models", [])}
            for n in list(self.models):
                if n.endswith(":latest"):
                    self.models.setdefault(n[:-7], self.models[n])
            try:
                async with self.session.get(self.endpoint + "/api/ps", headers=self.headers(), timeout=aiohttp.ClientTimeout(total=5)) as r:
                    self.loaded = (await r.json()).get("models", []) if r.status == 200 else []
            except Exception:
                self.loaded = []
            if self.version is None:
                try:
                    async with self.session.get(self.endpoint + "/api/version", headers=self.headers(), timeout=aiohttp.ClientTimeout(total=5)) as r:
                        self.version = (await r.json()).get("version") if r.status == 200 else None
                except Exception:
                    pass
            self.healthy, self.last_error = True, None
        except Exception as e:
            self.healthy, self.last_error = False, f"{e.__class__.__name__}: {str(e)[:120]}"
        self.checked_at = time.time()
        return self.healthy

    def has_model(self, name):
        return name in self.models or (name + ":latest") in self.models

    def status(self):
        return {"name": self.name, "kind": self.kind, "endpoint": self.endpoint, "enabled": self.enabled,
                "healthy": self.healthy, "error": self.last_error, "version": self.version,
                "cooldown_s": max(0, int(self.cooldown_until - time.time())), "secret_ref": self.secret_ref,
                "checked_at": self.checked_at, "models": sorted(n for n in self.models if ":" in n or n + ":latest" not in self.models),
                "loaded": [{"name": m.get("name"), "size_vram": m.get("size_vram"), "expires_at": m.get("expires_at")} for m in self.loaded],
                "capacity": self.capacity}

    # -- calls
    async def stream(self, path, body, timeout_s=600, key=None):
        """POST path with stream=true and yield each NDJSON object."""
        body = dict(body, stream=True)
        if "keep_alive" not in body and self.options.get("keep_alive"):
            body["keep_alive"] = self.options["keep_alive"]
        try:
            async with self.session.post(self.endpoint + path, json=body, headers=self.headers(key),
                                         timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=timeout_s)) as r:
                if r.status != 200:
                    text = (await r.text())[:300]
                    raise BackendError(r.status, _ollama_error(text), "model_not_found" if r.status == 404 else "backend_error")
                async for line in r.content:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if "error" in obj:
                        raise BackendError(500, str(obj["error"]))
                    yield obj
        except aiohttp.ClientConnectorError as e:
            self.fail()
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")
        except asyncio.TimeoutError:
            raise BackendError(504, f"{self.name} timed out", "timeout")

    async def call(self, path, body, timeout_s=600, key=None):
        """POST path without streaming and return the JSON object."""
        body = dict(body, stream=False)
        if "keep_alive" not in body and self.options.get("keep_alive") and path in ("/api/chat", "/api/generate", "/api/embed"):
            body["keep_alive"] = self.options["keep_alive"]
        try:
            async with self.session.post(self.endpoint + path, json=body, headers=self.headers(key),
                                         timeout=aiohttp.ClientTimeout(total=timeout_s, sock_connect=10)) as r:
                if r.status != 200:
                    text = (await r.text())[:300]
                    raise BackendError(r.status, _ollama_error(text), "model_not_found" if r.status == 404 else "backend_error")
                obj = await r.json()
                if isinstance(obj, dict) and "error" in obj:
                    raise BackendError(500, str(obj["error"]))
                return obj
        except aiohttp.ClientConnectorError as e:
            self.fail()
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")
        except asyncio.TimeoutError:
            raise BackendError(504, f"{self.name} timed out", "timeout")

    async def get(self, path):
        try:
            async with self.session.get(self.endpoint + path, headers=self.headers(), timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status, await r.json(content_type=None)
        except aiohttp.ClientConnectorError as e:
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")

    async def warm(self, model, keep_alive=None):
        body = {"model": model, "keep_alive": keep_alive or self.options.get("keep_alive") or "30m"}
        return await self.call("/api/generate", body, timeout_s=300)

    def capabilities(self, model):
        """What a model can do, from the backend's declared options (operators fill this in)."""
        caps = (self.options.get("capabilities") or {}).get(model) or (self.options.get("capabilities") or {}).get("*") or {}
        return caps


def _ollama_error(text):
    try:
        return json.loads(text).get("error", text)
    except Exception:
        return text


def usage_from(obj):
    """Token counts and durations (ms) from a final Ollama chunk."""
    def ms(k):
        v = obj.get(k)
        return int(v / 1e6) if v else None
    return {"tokens_in": obj.get("prompt_eval_count"), "tokens_out": obj.get("eval_count"),
            "total_ms": ms("total_duration"), "load_ms": ms("load_duration"),
            "prompt_ms": ms("prompt_eval_duration"), "eval_ms": ms("eval_duration"),
            "done_reason": obj.get("done_reason")}
