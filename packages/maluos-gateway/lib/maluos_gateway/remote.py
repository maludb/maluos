"""The remote backend kind (Phase 13 G2, docs/inference-node-api.md §6): another
MaluOS gateway (or a node service) reached over the network with the pairing
key this host holds in its vault. Speaks the Ollama-native API like the local
backend, with a bearer token, and tags every forwarded call with this node's
id and the desk-side call id so both ledgers can be joined. Not the cloud:
`remote_allowed` governs it, and the sensitivity gate applies."""
import json, time
import aiohttp

from .ollama import OllamaBackend, BackendError, _ollama_error


class RemoteBackend(OllamaBackend):
    is_cloud = False
    is_remote = True

    def __init__(self, row, session):
        super().__init__(row, session)
        self.key = None            # the pairing key, resolved by the gateway from the vault (system/remote-<name>)
        self.key_checked = 0
        self.node_id = None        # this node's id, stamped on forwarded calls
        self.node_name = None

    @property
    def max_concurrent(self):
        return int(self.capacity.get("max_concurrent") or 2)

    def headers(self, key=None, call=None):
        h = {"Authorization": f"Bearer {key or self.key}"} if (key or self.key) else {}
        if call is not None:
            h["X-MaluOS-Origin-Request"] = call.id
            h["X-MaluOS-Class"] = call.cls or ""
            if call.hints.get("max_wait") is not None:
                h["X-MaluOS-Max-Wait"] = str(call.hints["max_wait"])
            if call.hints.get("sensitivity"):
                h["X-MaluOS-Sensitivity"] = call.hints["sensitivity"]
        if self.node_id:
            h["X-MaluOS-Origin-Node"] = self.node_id
            h["X-MaluOS-Origin-Node-Name"] = self.node_name or ""
        return h

    async def refresh(self):
        if time.time() < self.cooldown_until:
            return False
        declared = self.options.get("models") or []
        try:
            if not self.key:
                raise BackendError(401, f"{self.name}: no pairing key in the vault (maluctl gateway backend add {self.name} URL --key ...)", "no_credential")
            async with self.session.get(self.endpoint + "/api/tags", headers=self.headers(), timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 401:
                    raise BackendError(401, f"{self.name}: the pairing key is refused", "bad_credential")
                if r.status != 200:
                    raise BackendError(r.status, (await r.text())[:200])
                tags = await r.json()
            found = {m["name"]: m for m in tags.get("models", []) if m.get("name") and "maluos" not in (m.get("details") or {}).get("family", "")}
            self.models = {n: found.get(n) or {"name": n, "model": n} for n in declared} if declared else found
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
            self.healthy, self.last_error = False, f"{e.__class__.__name__}: {str(e)[:120]}" if not isinstance(e, BackendError) else e.message
            self.models = {n: {"name": n, "model": n} for n in declared}
        self.checked_at = time.time()
        return self.healthy

    def status(self):
        d = super().status()
        d["remote"] = True
        d["paired"] = bool(self.key)
        return d

    def _raise(self, status, text):
        msg = _ollama_error(text)
        try:
            err = json.loads(text).get("error")
            if isinstance(err, dict):
                code = err.get("code") or "backend_error"
                msg = err.get("message") or msg
                cls = {"not_shared": "backend_unavailable", "model_not_found": "model_not_found", "unauthorized": "bad_credential", "policy": "capability",
                       "queue_full": "backend_unavailable", "wait_exceeds": "timeout", "local_unavailable": "backend_unavailable"}.get(code, "backend_error")
                raise BackendError(status if status in (401, 403, 404, 429, 503, 504) else 502, f"{self.name}: {msg}", cls)
        except (ValueError, AttributeError):
            pass
        raise BackendError(status if status in (401, 403, 404, 429, 503, 504) else 502, f"{self.name}: {msg}", "model_not_found" if status == 404 else "backend_error")

    async def stream(self, path, body, timeout_s=600, key=None, call=None):
        if not (key or self.key):
            raise BackendError(401, f"{self.name}: no pairing key", "no_credential")
        body = dict(body, stream=True)
        try:
            async with self.session.post(self.endpoint + path, json=body, headers=self.headers(key, call),
                                         timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=timeout_s)) as r:
                if r.status != 200:
                    self._raise(r.status, (await r.text())[:400])
                rid = r.headers.get("X-MaluOS-Request")
                async for line in r.content:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if "error" in obj:
                        raise BackendError(500, f"{self.name}: {obj['error']}", obj.get("error_class") or "backend_error")
                    if obj.get("done") and rid:
                        obj["provider_request_id"] = rid
                    yield obj
        except aiohttp.ClientConnectorError as e:
            self.fail()
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")
        except TimeoutError:
            raise BackendError(504, f"{self.name} timed out", "timeout")

    async def call(self, path, body, timeout_s=600, key=None, call=None):
        if not (key or self.key):
            raise BackendError(401, f"{self.name}: no pairing key", "no_credential")
        body = dict(body, stream=False)
        try:
            async with self.session.post(self.endpoint + path, json=body, headers=self.headers(key, call),
                                         timeout=aiohttp.ClientTimeout(total=timeout_s, sock_connect=10)) as r:
                if r.status != 200:
                    self._raise(r.status, (await r.text())[:400])
                obj = await r.json()
                if isinstance(obj, dict) and "error" in obj:
                    raise BackendError(500, f"{self.name}: {obj['error']}")
                if isinstance(obj, dict) and r.headers.get("X-MaluOS-Request"):
                    obj["provider_request_id"] = r.headers["X-MaluOS-Request"]
                return obj
        except aiohttp.ClientConnectorError as e:
            self.fail()
            raise BackendError(503, f"{self.name} unreachable: {e}", "backend_unavailable")
        except TimeoutError:
            raise BackendError(504, f"{self.name} timed out", "timeout")
