"""
Seal the secrets already in the auth store, or report on them.

    python -m app.seal_store --new-key     print a fresh key for MALUDB_STORE_KEY; touches nothing
    python -m app.seal_store --check       how many secrets are sealed / plain; touches nothing
    python -m app.seal_store               seal every plain secret (needs MALUDB_STORE_KEY)
    python -m app.seal_store --reseal      re-seal everything under the FIRST key (after rotation)

The store is the file named by MALUDB_AUTH_STORE (default: data/auth.db, as the service uses).
Runs in one transaction: every row is sealed, or none is. Every sealed value is opened again
before the commit, so a wrong key cannot leave a store that the service is unable to read.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from app import config, store_crypto

# (table, primary key column, secret column)
SECRET_COLUMNS = [
    ("users", "id", "pg_password"),
    ("user_provider_keys", "rowid", "api_key"),
    ("model_prompts", "rowid", "api_key"),
]


def _store_path() -> str:
    return config.AUTH_STORE_PATH


def survey(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    out = {}
    for table, _, column in SECRET_COLUMNS:
        rows = conn.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} <> ''").fetchall()
        sealed = sum(1 for (v,) in rows if store_crypto.is_sealed(v))
        out[f"{table}.{column}"] = {"sealed": sealed, "plain": len(rows) - sealed}
    return out


def seal_all(conn: sqlite3.Connection, reseal: bool = False) -> int:
    """Seal plain secrets (and, with reseal, re-seal sealed ones under the first key). Returns rows changed."""
    if not store_crypto.enabled():
        raise store_crypto.StoreKeyError(f"{store_crypto.ENV_KEY} is not set — nothing to seal with.")
    changed = 0
    with conn:  # one transaction
        for table, pk, column in SECRET_COLUMNS:
            rows = conn.execute(
                f"SELECT {pk}, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} <> ''"
            ).fetchall()
            for key, stored in rows:
                if store_crypto.is_sealed(stored) and not reseal:
                    continue
                secret = store_crypto.unseal(stored)
                sealed = store_crypto.seal(secret)
                if store_crypto.unseal(sealed) != secret:  # never commit what cannot be opened
                    raise store_crypto.StoreKeyError(f"{table}.{column}: a sealed value did not open to what went in.")
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE {pk} = ?", (sealed, key))
                changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seal the secrets in the MaluDB auth store.")
    parser.add_argument("--new-key", action="store_true", help="print a new key and exit")
    parser.add_argument("--check", action="store_true", help="report sealed/plain counts and exit")
    parser.add_argument("--reseal", action="store_true", help="re-seal everything under the first key")
    args = parser.parse_args(argv)

    if args.new_key:
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
        return 0

    path = _store_path()
    if not os.path.isfile(path):
        print(f"No auth store at {path} (set MALUDB_AUTH_STORE).", file=sys.stderr)
        return 1
    conn = sqlite3.connect(path)
    try:
        if args.check:
            for name, counts in survey(conn).items():
                print(f"{name}: {counts['sealed']} sealed, {counts['plain']} plain")
            print(f"{store_crypto.ENV_KEY}: {'set' if store_crypto.enabled() else 'NOT set'}")
            return 0
        try:
            changed = seal_all(conn, reseal=args.reseal)
        except store_crypto.StoreKeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Sealed {changed} secret(s) in {path}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
