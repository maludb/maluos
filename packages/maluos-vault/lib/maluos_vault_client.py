"""Client for the MaluOS vault over its Unix socket. Identity is the calling
process's uid (peer credentials); nothing to configure. Used by maluctl, the
first-boot components and, from slice 2, the inference gateway."""
import http.client, json, os, socket, urllib.parse

SOCKET = os.environ.get("MALUOS_VAULT_SOCKET", "/run/maluos/vault.sock")


class VaultError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"{code}: {message}"); self.status, self.code, self.message = status, code, message


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=30):
        super().__init__("maluos-vault", timeout=timeout); self.path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(self.timeout); s.connect(self.path); self.sock = s


class Vault:
    def __init__(self, socket_path=None, on_behalf_of=None, timeout=30):
        self.socket_path, self.on_behalf_of, self.timeout = socket_path or SOCKET, on_behalf_of, timeout

    def request(self, method, path, body=None, query=None):
        if query:
            path += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "", False)})
        headers = {"Content-Type": "application/json"}
        if self.on_behalf_of:
            headers["X-MaluOS-Principal"] = self.on_behalf_of
        data = json.dumps(body).encode() if body is not None else None
        c = _UnixConn(self.socket_path, self.timeout)
        try:
            c.request(method, path, body=data, headers=headers)
            r = c.getresponse(); raw = r.read()
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise VaultError(0, "unavailable", f"vault socket {self.socket_path}: {e.strerror or e}")
        finally:
            c.close()
        try:
            obj = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise VaultError(r.status, "bad_response", raw[:200].decode(errors="replace"))
        if r.status >= 400:
            raise VaultError(r.status, obj.get("error", "error"), obj.get("message", ""))
        return obj

    def available(self):
        return os.path.exists(self.socket_path)

    # convenience
    def health(self):             return self.request("GET", "/v1/health")
    def whoami(self):             return self.request("GET", "/v1/whoami")
    def compartments(self):       return self.request("GET", "/v1/compartments")["compartments"]
    def create_compartment(self, name, owner=None, scope=None, lock_mode=None):
        return self.request("POST", "/v1/compartments", {"name": name, "owner": owner, "scope": scope, "lock_mode": lock_mode})
    def lock(self, name, locked=True):
        return self.request("POST", f"/v1/compartments/{q(name)}/{'lock' if locked else 'unlock'}")
    def secrets(self, compartment=None, all=False):
        return self.request("GET", "/v1/secrets", query={"compartment": compartment, "all": "1" if all else None})["secrets"]
    def add(self, name, value, compartment=None, kind=None, provider=None, env_var=None, expires_at=None, upsert=False, grace_hours=0):
        return self.request("POST", "/v1/secrets", {"name": name, "value": value, "compartment": compartment, "kind": kind,
                                                    "provider": provider, "env_var": env_var, "expires_at": expires_at,
                                                    "upsert": upsert, "grace_hours": grace_hours})
    def get(self, ref):           return self.request("GET", f"/v1/secrets/{q(ref)}")
    def value(self, ref, mode="read", purpose=None, previous=False):
        return self.request("GET", f"/v1/secrets/{q(ref)}/value", query={"mode": mode, "purpose": purpose, "previous": "1" if previous else None})
    def use(self, ref, purpose=None): return self.value(ref, "use", purpose)
    def rotate(self, ref, value, grace_hours=0, **meta):
        return self.request("POST", f"/v1/secrets/{q(ref)}/rotate", dict(meta, value=value, grace_hours=grace_hours))
    def delete(self, ref):        return self.request("DELETE", f"/v1/secrets/{q(ref)}")
    def grants(self, ref):        return self.request("GET", f"/v1/secrets/{q(ref)}/grants")["grants"]
    def grant(self, ref, grantee_kind, grantee_ref, level="use", expires_at=None, budget=None):
        return self.request("POST", f"/v1/secrets/{q(ref)}/grants", {"grantee_kind": grantee_kind, "grantee_ref": grantee_ref,
                                                                      "level": level, "expires_at": expires_at, "budget": budget})
    def revoke(self, ref, grantee_kind, grantee_ref):
        return self.request("POST", f"/v1/secrets/{q(ref)}/revoke", {"grantee_kind": grantee_kind, "grantee_ref": grantee_ref})
    def ledger(self, **query):    return self.request("GET", "/v1/ledger", query=query)["events"]


def q(s):
    return urllib.parse.quote(str(s), safe="")
