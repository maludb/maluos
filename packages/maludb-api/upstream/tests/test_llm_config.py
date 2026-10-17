"""
Tests for the LLM config router — /v1/llm/catalog, /v1/llm/providers,
/v1/llm/models — and the resolution helper (app/helpers/llm_resolve.py).

No live Postgres needed: the auth store points at a temp SQLite database and
the tenant connection made by require_auth is mocked out (the /v1/llm
handlers never touch it).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.helpers.llm_resolve import resolve_embed_config, resolve_task_config

_TOKEN_BODY = "llm_config_test_token"
_TOKEN = f"malu_{_TOKEN_BODY}"
_USER_ID = 7
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture()
def store(tmp_path: Path):
    """Temporary auth store with the seeded catalog and one user token."""
    from app.auth_store import AuthStore

    s = AuthStore(str(tmp_path / "test_auth.db"))
    s.init_db()
    s.connection.execute(
        """INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            hashlib.sha256(_TOKEN_BODY.encode()).hexdigest(),
            "llm_test_",
            _USER_ID,
            "executor",
            "testdb",
            "testuser",
            "testpass",
        ),
    )
    s.connection.commit()
    return s


@pytest.fixture()
def client(store) -> TestClient:
    """TestClient with the auth store mocked and the tenant Postgres stubbed."""
    from app.main import app

    with (
        patch("app.auth.get_auth_store", return_value=store),
        patch("app.routers.llm_config.get_auth_store", return_value=store),
        patch("app.auth.TenantConnection") as tc,
    ):
        tc.return_value.connect.return_value = MagicMock()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Endpoint registration — 401 (not 404) without a token
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/llm/catalog"),
    ("GET", "/v1/llm/providers"),
    ("PUT", "/v1/llm/providers/openai"),
    ("DELETE", "/v1/llm/providers/openai"),
    ("GET", "/v1/llm/models"),
    ("PUT", "/v1/llm/models/extract"),
    ("DELETE", "/v1/llm/models/extract"),
]


class TestLlmRouterRegistered:
    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        from app.main import app

        anon = TestClient(app, raise_server_exceptions=False)
        resp = anon.request(method, path)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
        assert resp.json()["error"]["code"] == "auth_missing"


# ---------------------------------------------------------------------------
# GET /v1/llm/catalog
# ---------------------------------------------------------------------------


class TestCatalog:
    def test_catalog_is_seeded(self, client: TestClient):
        resp = client.get("/v1/llm/catalog", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["tasks"]) == {"embed", "extract", "skill_extract", "query_parse", "answer"}
        by_key = {(m["model_name"], m["task"]): m for m in data["models"]}
        assert ("gpt-4o", "extract") in by_key
        assert ("claude-sonnet", "extract") in by_key
        assert by_key[("gpt-4o", "extract")]["provider"] == "openai"
        assert by_key[("gpt-4o", "extract")]["has_system_prompt"] is True
        assert by_key[("text-embedding-3-small", "embed")]["has_system_prompt"] is False
        assert by_key[("gpt-4o", "answer")]["has_system_prompt"] is False  # M1 builds the answer prompt itself

    def test_catalog_never_returns_prompt_text_or_keys(self, client: TestClient):
        resp = client.get("/v1/llm/catalog", headers=_HEADERS)
        # prompt bodies stay out of the listing (only has_system_prompt flags)
        assert "memory-extraction service" not in resp.text
        assert "api_key" not in resp.text

    def test_catalog_reflects_key_and_choice_state(self, client: TestClient):
        client.put("/v1/llm/providers/openai", headers=_HEADERS, json={"api_key": "sk-x"})
        client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "gpt-4o"})
        data = client.get("/v1/llm/catalog", headers=_HEADERS).json()
        by_key = {(m["model_name"], m["task"]): m for m in data["models"]}
        assert by_key[("gpt-4o", "extract")]["key_set"] is True
        assert by_key[("gpt-4o", "extract")]["is_choice"] is True
        assert by_key[("claude-sonnet", "extract")]["key_set"] is False
        assert by_key[("claude-sonnet", "extract")]["is_choice"] is False


# ---------------------------------------------------------------------------
# /v1/llm/providers
# ---------------------------------------------------------------------------


class TestProviderKeys:
    def test_put_and_list_round_trip(self, client: TestClient):
        resp = client.put("/v1/llm/providers/openai", headers=_HEADERS, json={"api_key": "sk-secret-123"})
        assert resp.status_code == 200
        assert resp.json()["provider"] == {"provider": "openai", "key_set": True, "base_url": None}

        listed = client.get("/v1/llm/providers", headers=_HEADERS)
        assert listed.status_code == 200
        providers = listed.json()["providers"]
        assert len(providers) == 1
        assert providers[0]["provider"] == "openai"
        assert providers[0]["key_set"] is True

    def test_key_value_never_in_any_response(self, client: TestClient):
        put = client.put("/v1/llm/providers/openai", headers=_HEADERS, json={"api_key": "sk-secret-123"})
        assert "sk-secret-123" not in put.text
        for path in ("/v1/llm/providers", "/v1/llm/catalog", "/v1/llm/models"):
            assert "sk-secret-123" not in client.get(path, headers=_HEADERS).text

    def test_update_without_api_key_preserves_stored_key(self, client: TestClient, store):
        client.put("/v1/llm/providers/ollama", headers=_HEADERS, json={"api_key": "ol-key"})
        resp = client.put("/v1/llm/providers/ollama", headers=_HEADERS, json={"base_url": "http://my-ollama:11434/v1"})
        assert resp.status_code == 200
        assert resp.json()["provider"]["base_url"] == "http://my-ollama:11434/v1"
        row = store.user_provider_key(_USER_ID, "ollama")
        assert row["api_key"] == "ol-key"

    def test_first_set_requires_api_key(self, client: TestClient):
        resp = client.put("/v1/llm/providers/openai", headers=_HEADERS, json={})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_field"

    def test_unknown_provider_rejected(self, client: TestClient):
        resp = client.put("/v1/llm/providers/closedai", headers=_HEADERS, json={"api_key": "sk-x"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_failed"
        assert "openai" in resp.json()["error"]["message"]

    def test_delete_key(self, client: TestClient):
        client.put("/v1/llm/providers/openai", headers=_HEADERS, json={"api_key": "sk-x"})
        resp = client.delete("/v1/llm/providers/openai", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True, "provider": "openai"}
        again = client.delete("/v1/llm/providers/openai", headers=_HEADERS)
        assert again.status_code == 404
        assert again.json()["error"]["code"] == "not_found"

    def test_keys_are_per_user(self, client: TestClient, store):
        client.put("/v1/llm/providers/openai", headers=_HEADERS, json={"api_key": "sk-x"})
        assert store.user_provider_key(_USER_ID, "openai") is not None
        assert store.user_provider_key(_USER_ID + 1, "openai") is None


# ---------------------------------------------------------------------------
# /v1/llm/models
# ---------------------------------------------------------------------------


class TestModelChoices:
    def test_put_choice_warns_without_key(self, client: TestClient):
        resp = client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "claude-sonnet"})
        assert resp.status_code == 200
        choice = resp.json()["choice"]
        assert choice["model_name"] == "claude-sonnet"
        assert choice["provider"] == "anthropic"
        assert choice["key_set"] is False
        assert "anthropic" in choice["warning"]

    def test_put_choice_with_key_has_no_warning(self, client: TestClient):
        client.put("/v1/llm/providers/anthropic", headers=_HEADERS, json={"api_key": "sk-ant"})
        resp = client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "claude-sonnet"})
        choice = resp.json()["choice"]
        assert choice["key_set"] is True
        assert "warning" not in choice

    def test_unknown_model_rejected(self, client: TestClient):
        resp = client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "gpt-99"})
        assert resp.status_code == 422
        assert "catalog" in resp.json()["error"]["message"]

    def test_model_must_match_task(self, client: TestClient):
        # an embed-only model is not valid for extract
        resp = client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "text-embedding-3-small"})
        assert resp.status_code == 422

    def test_missing_model_name(self, client: TestClient):
        resp = client.put("/v1/llm/models/extract", headers=_HEADERS, json={})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_field"

    def test_list_shows_choices_and_defaults(self, client: TestClient):
        client.put(
            "/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "claude-sonnet", "system_prompt": "custom"}
        )
        models = {m["task"]: m for m in client.get("/v1/llm/models", headers=_HEADERS).json()["models"]}
        assert models["extract"]["model_name"] == "claude-sonnet"
        assert models["extract"]["chosen"] is True
        assert models["extract"]["system_prompt_override"] is True
        # No choice for skill_extract / embed -> server defaults
        assert models["skill_extract"]["chosen"] is False
        assert models["embed"]["chosen"] is False

    def test_list_defaults_to_legacy_extract_model(self, client: TestClient):
        models = {m["task"]: m for m in client.get("/v1/llm/models", headers=_HEADERS).json()["models"]}
        assert models["extract"]["model_name"] == "chatgpt-4o"
        assert models["extract"]["chosen"] is False

    def test_delete_choice(self, client: TestClient):
        client.put("/v1/llm/models/extract", headers=_HEADERS, json={"model_name": "gpt-4o"})
        resp = client.delete("/v1/llm/models/extract", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True, "task": "extract"}
        again = client.delete("/v1/llm/models/extract", headers=_HEADERS)
        assert again.status_code == 404


# ---------------------------------------------------------------------------
# Resolution helper (no HTTP)
# ---------------------------------------------------------------------------


class TestResolveTaskConfig:
    def test_explicit_model_prefers_legacy_model_prompts(self, store):
        # A legacy row whose name collides with a catalog model must win.
        store.connection.execute(
            """INSERT INTO model_prompts (model_name, api_format, system_prompt, base_url, api_key)
               VALUES ('gpt-4o', 'openai', 'legacy prompt', 'https://legacy.example/v1', 'legacy-key')""",
        )
        store.connection.commit()
        cfg = resolve_task_config(store, _USER_ID, "extract", "gpt-4o")
        assert cfg["source"] == "model_prompts"
        assert cfg["base_url"] == "https://legacy.example/v1"
        assert cfg["api_key"] == "legacy-key"

    def test_explicit_model_falls_back_to_catalog(self, store):
        store.upsert_user_provider_key(_USER_ID, "anthropic", "sk-ant", None)
        cfg = resolve_task_config(store, _USER_ID, "extract", "claude-sonnet")
        assert cfg["source"] == "catalog_explicit"
        assert cfg["api_format"] == "anthropic"
        assert cfg["model_identifier"] == "claude-sonnet-4-6"
        assert cfg["api_key"] == "sk-ant"
        assert "{{ENTITY_TYPES}}" in cfg["system_prompt"]

    def test_user_choice_with_overrides(self, store):
        store.upsert_user_provider_key(_USER_ID, "ollama", "ol-key", "http://my-box:11434/v1")
        store.upsert_user_model_choice(_USER_ID, "extract", "ollama-local", "my custom prompt")
        cfg = resolve_task_config(store, _USER_ID, "extract")
        assert cfg["source"] == "user_choice"
        assert cfg["model_name"] == "ollama-local"
        assert cfg["base_url"] == "http://my-box:11434/v1"  # user base_url override
        assert cfg["system_prompt"] == "my custom prompt"  # user prompt override

    def test_nothing_configured_returns_none(self, store):
        assert resolve_task_config(store, _USER_ID, "extract") is None
        assert resolve_task_config(store, _USER_ID, "extract", "no-such-model") is None

    def test_skill_extract_task_uses_skill_prompt(self, store):
        store.upsert_user_provider_key(_USER_ID, "openai", "sk-x", None)
        cfg = resolve_task_config(store, _USER_ID, "skill_extract", "gpt-4o")
        assert cfg["source"] == "catalog_explicit"
        assert cfg["system_prompt"] != ""
        # skill prompt differs from the extract prompt
        extract_cfg = resolve_task_config(store, _USER_ID, "extract", "gpt-4o")
        assert cfg["system_prompt"] != extract_cfg["system_prompt"]


class TestResolveEmbedConfig:
    def test_unset_returns_empty(self, store):
        assert resolve_embed_config(store, _USER_ID) == {}

    def test_choice_without_key_returns_empty(self, store):
        store.upsert_user_model_choice(_USER_ID, "embed", "text-embedding-3-small", None)
        assert resolve_embed_config(store, _USER_ID) == {}

    def test_choice_with_key(self, store):
        store.upsert_user_provider_key(_USER_ID, "openai", "sk-x", None)
        store.upsert_user_model_choice(_USER_ID, "embed", "text-embedding-3-small", None)
        cfg = resolve_embed_config(store, _USER_ID)
        assert cfg == {
            "embedding_base_url": "https://api.openai.com/v1",
            "embedding_token": "sk-x",
            "embedding_model": "text-embedding-3-small",
        }
