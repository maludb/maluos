"""
Secrets at rest in the auth store (app/store_crypto.py, app/seal_store.py).

The promises under test: with no key nothing changes; with a key every write is sealed and every
read still opens legacy plain rows; a sealed row without its key FAILS (never yields the token
text as the secret); migration is all-or-nothing and idempotent; rotation works.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app import seal_store, store_crypto
from app.auth_store import AuthStore
from app.store_crypto import PREFIX, SecretFormatError, StoreKeyError, seal, unseal


@pytest.fixture
def key(monkeypatch):
    k = Fernet.generate_key().decode()
    monkeypatch.setenv(store_crypto.ENV_KEY, k)
    return k


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv(store_crypto.ENV_KEY, raising=False)


@pytest.fixture
def store(tmp_path):
    s = AuthStore(str(tmp_path / "auth.db"))
    s.init_db()
    return s


def _add_user(store: AuthStore, token_hash: str, password: str | None) -> None:
    store.connection.execute(
        "INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password) "
        "VALUES (?, 'abcd1234', 1, 'user', 'db', 'role', ?)",
        (token_hash, password),
    )
    store.connection.commit()


def _raw(store: AuthStore, sql: str):
    return store.connection.execute(sql).fetchone()[0]


class TestSealUnseal:
    def test_without_a_key_nothing_changes(self, no_key):
        assert seal("s3cret") == "s3cret"
        assert unseal("s3cret") == "s3cret"
        assert not store_crypto.enabled()

    def test_with_a_key_the_stored_value_is_not_the_secret_and_opens_again(self, key):
        stored = seal("s3cret")
        assert stored.startswith(PREFIX) and "s3cret" not in stored
        assert unseal(stored) == "s3cret"
        assert seal("s3cret") != stored  # Fernet is randomised: equal secrets do not look equal

    def test_empty_and_none_stay_visible_as_not_set(self, key):
        assert seal(None) is None and seal("") == ""
        assert unseal(None) is None and unseal("") == ""

    def test_a_legacy_plain_value_still_reads_once_a_key_is_set(self, key):
        assert unseal("plain-from-before") == "plain-from-before"

    def test_a_sealed_value_without_its_key_fails_and_never_falls_back(self, key, monkeypatch):
        stored = seal("s3cret")
        monkeypatch.delenv(store_crypto.ENV_KEY)
        with pytest.raises(StoreKeyError):
            unseal(stored)

    def test_the_wrong_key_fails(self, key, monkeypatch):
        stored = seal("s3cret")
        monkeypatch.setenv(store_crypto.ENV_KEY, Fernet.generate_key().decode())
        with pytest.raises(StoreKeyError):
            unseal(stored)

    def test_a_malformed_key_is_named_not_swallowed(self, monkeypatch):
        monkeypatch.setenv(store_crypto.ENV_KEY, "not-a-key")
        with pytest.raises(StoreKeyError, match="MALUDB_STORE_KEY"):
            seal("s3cret")

    def test_rotation_the_first_key_seals_and_every_key_opens(self, key, monkeypatch):
        old = seal("s3cret")
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv(store_crypto.ENV_KEY, f"{new_key},{key}")
        assert unseal(old) == "s3cret"
        resealed = seal("s3cret")
        monkeypatch.setenv(store_crypto.ENV_KEY, new_key)  # the old key is dropped
        assert unseal(resealed) == "s3cret"
        with pytest.raises(StoreKeyError):
            unseal(old)

    def test_with_no_key_a_secret_that_looks_sealed_is_refused(self, no_key):
        with pytest.raises(SecretFormatError):
            seal(PREFIX + "anything")


class TestAuthStore:
    def test_a_provider_key_is_sealed_on_disk_and_plain_to_the_caller(self, store, key):
        store.upsert_user_provider_key(1, "openai", "sk-test-123", None)
        on_disk = _raw(store, "SELECT api_key FROM user_provider_keys")
        assert on_disk.startswith(PREFIX) and "sk-test-123" not in on_disk
        assert store.user_provider_key(1, "openai")["api_key"] == "sk-test-123"
        assert store.list_user_provider_keys(1)[0]["key_set"]

    def test_updating_the_base_url_keeps_the_key_and_does_not_seal_it_twice(self, store, key):
        store.upsert_user_provider_key(1, "openai", "sk-test-123", None)
        store.upsert_user_provider_key(1, "openai", None, "https://proxy.example/v1")
        row = store.user_provider_key(1, "openai")
        assert row["api_key"] == "sk-test-123" and row["base_url"] == "https://proxy.example/v1"

    def test_resolve_token_opens_a_sealed_password_and_a_legacy_plain_one(self, store, key):
        _add_user(store, "hash-sealed", seal("pg-pass"))
        _add_user(store, "hash-plain", "pg-pass-old")
        assert store.resolve_token("hash-sealed")["pg_password"] == "pg-pass"
        assert store.resolve_token("hash-plain")["pg_password"] == "pg-pass-old"

    def test_without_the_key_a_sealed_token_cannot_be_resolved(self, store, key, monkeypatch):
        _add_user(store, "hash-sealed", seal("pg-pass"))
        monkeypatch.delenv(store_crypto.ENV_KEY)
        with pytest.raises(StoreKeyError):
            store.resolve_token("hash-sealed")

    def test_with_no_key_the_store_behaves_as_it_always_did(self, store, no_key):
        store.upsert_user_provider_key(1, "openai", "sk-test-123", None)
        assert _raw(store, "SELECT api_key FROM user_provider_keys") == "sk-test-123"


class TestSealStoreCommand:
    def _fill(self, store: AuthStore) -> None:
        _add_user(store, "h1", "pg-one")
        _add_user(store, "h2", "pg-two")
        store.connection.execute(
            "INSERT INTO user_provider_keys (user_id, provider, api_key) VALUES (1, 'openai', 'sk-plain')"
        )
        store.connection.commit()

    def test_it_seals_everything_once_and_a_second_run_changes_nothing(self, store, no_key, monkeypatch):
        self._fill(store)  # written plain, before any key existed
        monkeypatch.setenv(store_crypto.ENV_KEY, Fernet.generate_key().decode())
        assert seal_store.survey(store.connection)["users.pg_password"] == {"sealed": 0, "plain": 2}
        assert seal_store.seal_all(store.connection) == 3
        assert seal_store.seal_all(store.connection) == 0
        counts = seal_store.survey(store.connection)
        assert counts["users.pg_password"] == {"sealed": 2, "plain": 0}
        assert counts["user_provider_keys.api_key"] == {"sealed": 1, "plain": 0}
        assert store.resolve_token("h1")["pg_password"] == "pg-one"
        assert store.user_provider_key(1, "openai")["api_key"] == "sk-plain"

    def test_without_a_key_it_refuses_and_touches_nothing(self, store, no_key):
        self._fill(store)
        with pytest.raises(StoreKeyError):
            seal_store.seal_all(store.connection)
        assert _raw(store, "SELECT pg_password FROM users WHERE token_hash = 'h1'") == "pg-one"

    def test_reseal_moves_every_secret_under_the_new_first_key(self, store, key, monkeypatch):
        self._fill(store)
        seal_store.seal_all(store.connection)
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv(store_crypto.ENV_KEY, f"{new_key},{key}")
        assert seal_store.seal_all(store.connection, reseal=True) == 3
        monkeypatch.setenv(store_crypto.ENV_KEY, new_key)
        assert store.resolve_token("h2")["pg_password"] == "pg-two"

    def test_a_failure_part_way_rolls_the_whole_store_back(self, store, key, monkeypatch):
        self._fill(store)
        real_seal, calls = store_crypto.seal, {"n": 0}

        def failing(value):
            calls["n"] += 1
            if calls["n"] == 2:
                raise StoreKeyError("boom")
            return real_seal(value)

        monkeypatch.setattr(seal_store.store_crypto, "seal", failing)
        with pytest.raises(StoreKeyError):
            seal_store.seal_all(store.connection)
        assert seal_store.survey(store.connection)["users.pg_password"] == {"sealed": 0, "plain": 2}


class TestOverHttp:
    def test_a_store_that_cannot_be_opened_answers_503_and_names_the_setting(self, monkeypatch):
        from fastapi.testclient import TestClient

        import app.auth as auth
        from app.main import app

        class Locked:
            def resolve_token(self, _hash):
                raise StoreKeyError("The auth store holds sealed secrets but MALUDB_STORE_KEY is not set.")

        monkeypatch.setattr(auth, "get_auth_store", lambda: Locked())
        r = TestClient(app, raise_server_exceptions=False).get(
            "/v1/subjects", headers={"Authorization": "Bearer malu_" + "a" * 40}
        )
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "store_key_unavailable"
        assert "MALUDB_STORE_KEY" in r.json()["error"]["message"]
