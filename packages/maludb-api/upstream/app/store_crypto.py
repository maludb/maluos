"""
Secrets at rest in the SQLite auth store.

The store holds three kinds of secret in plain columns: a tenant's Postgres password
(`users.pg_password`), a user's provider API keys (`user_provider_keys.api_key`) and a model
prompt's own key (`model_prompts.api_key`). Anyone who can read the file — a backup, a copied
disk, a stray `scp` — reads them all.

With MALUDB_STORE_KEY set, those columns hold `enc:v1:<Fernet token>` instead. What this buys is
exactly that: the FILE alone is no longer enough. It is not a defence against someone who
controls the running service or reads its environment; the key lives next to the process.

Rules, so that turning this on can never lock a tenant out:

- No key configured  → values are written and read as they always were. Nothing changes.
- Key configured     → every write is sealed; a read accepts a sealed value OR a legacy plain one,
                       so an existing store keeps working and is sealed row by row as rows are
                       rewritten — or all at once with `python -m app.seal_store`.
- Sealed value, no key (or the wrong key) → StoreKeyError. Never a silent fallback to treating
                       the token text as the secret.
- Rotation           → MALUDB_STORE_KEY may hold several comma-separated keys: the first seals,
                       all of them open. Add the new key in front, run `python -m app.seal_store
                       --reseal`, then drop the old one.

LOSING THE KEY LOSES THE SECRETS: every token would have to be minted again and every provider
key re-entered. Back the key up somewhere the store's backups are not.
"""

from __future__ import annotations

import os
from functools import lru_cache

PREFIX = "enc:v1:"
ENV_KEY = "MALUDB_STORE_KEY"


class StoreKeyError(RuntimeError):
    """A sealed value cannot be opened: the key is missing, malformed or not the one that sealed it."""


class SecretFormatError(ValueError):
    """A secret that cannot be stored as given (it looks like a sealed value, and no key is set)."""


@lru_cache(maxsize=4)
def _cipher(raw: str):
    """MultiFernet for a MALUDB_STORE_KEY value; cached per value so rotation needs only a restart."""
    try:
        from cryptography.fernet import Fernet, MultiFernet
    except ImportError as exc:  # pragma: no cover - the dependency is declared in pyproject
        raise StoreKeyError(f"{ENV_KEY} is set but the 'cryptography' package is not installed.") from exc
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError) as exc:
        raise StoreKeyError(f"{ENV_KEY} is not a valid key. Make one with: python -m app.seal_store --new-key") from exc


def _configured():
    raw = os.environ.get(ENV_KEY, "").strip()
    return _cipher(raw) if raw else None


def enabled() -> bool:
    return _configured() is not None


def is_sealed(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(value: str | None) -> str | None:
    """What to store for a secret. None and '' stay as they are: 'no key set' must remain visible
    to the `IS NOT NULL AND <> ''` checks the listings use."""
    if value is None or value == "":
        return value
    cipher = _configured()
    if cipher is None:
        if value.startswith(PREFIX):
            # Stored as-is it would later be read as a sealed value and fail to open.
            raise SecretFormatError(f'A secret may not begin with "{PREFIX}" while {ENV_KEY} is not set.')
        return value
    return PREFIX + cipher.encrypt(value.encode()).decode()


def unseal(value: str | None) -> str | None:
    """The secret behind a stored value. A legacy plain value is returned unchanged."""
    if not is_sealed(value):
        return value
    cipher = _configured()
    if cipher is None:
        raise StoreKeyError(f"The auth store holds sealed secrets but {ENV_KEY} is not set.")
    from cryptography.fernet import InvalidToken

    try:
        return cipher.decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise StoreKeyError(f"A sealed secret could not be opened with the configured {ENV_KEY}.") from exc
