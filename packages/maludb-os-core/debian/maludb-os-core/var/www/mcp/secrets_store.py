"""Read side of the tenant secrets store for Python jobs (the IMAP poller, provider clients).

The writer is PHP (app/secrets.php); the format is its: "v<key_version>:" + base64(iv[12] +
tag[16] + ciphertext), AES-256-GCM, the secret's NAME as additional authenticated data. The key
is SECRETS_KEY (v1) / SECRETS_KEY_V<n> in config/.env, read through db.ENV like every other key.

A job decrypts a credential only at the moment it uses it, never logs it, and never returns it
from a tool — the records MCP role has no grant on tenant_secrets at all.
"""
from __future__ import annotations

import base64
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import db


def _key(version: int) -> bytes:
    raw = db.ENV.get("SECRETS_KEY" if version == 1 else f"SECRETS_KEY_V{version}", "")
    if len(raw) != 64:
        raise RuntimeError(f"The secrets key (version {version}) is not configured.")
    return bytes.fromhex(raw)


def decrypt(name: str, stored: str) -> str:
    found = re.match(r"^v(\d+):(.+)$", stored, re.S)
    if not found:
        raise ValueError("Unreadable secret.")
    blob = base64.b64decode(found.group(2))
    iv, tag, cipher = blob[:12], blob[12:28], blob[28:]
    # AESGCM wants ciphertext followed by the tag; PHP stores the tag first.
    return AESGCM(_key(int(found.group(1)))).decrypt(iv, cipher + tag, name.encode()).decode()


async def read(conn, secret_id: int) -> str | None:
    """The plain secret for a job that must use it, or None when it is gone or revoked."""
    row = await conn.fetchrow(
        "SELECT name, ciphertext FROM tenant_secrets WHERE id = $1 AND revoked_at IS NULL", secret_id)
    return None if row is None else decrypt(row["name"], row["ciphertext"])
