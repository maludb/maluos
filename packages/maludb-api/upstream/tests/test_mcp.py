"""
Tests for the MCP endpoint — POST /mcp (stateless Streamable HTTP, spec 2025-06-18).

No live Postgres needed: the auth store points at a temp SQLite database, the
tenant connection is mocked, and tool tests patch the db helpers / pipeline
cores imported into app.routers.mcp.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.routers.mcp import TOOLS

_TOKEN_BODY = "mcp_test_token"
_TOKEN = f"malu_{_TOKEN_BODY}"
_USER_ID = 9
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}

_READ_TOOLS = {
    "search_memory",
    "find_subjects",
    "explore_subject",
    "get_document",
    "find_notes",
    "find_skills",
    "get_skill",
}
_WRITE_TOOLS = {"store_memory", "store_document"}


@pytest.fixture()
def store(tmp_path: Path):
    """Temporary auth store with one user token."""
    from app.auth_store import AuthStore

    s = AuthStore(str(tmp_path / "test_auth.db"))
    s.init_db()
    s.connection.execute(
        """INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            hashlib.sha256(_TOKEN_BODY.encode()).hexdigest(),
            "mcp_test_",
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
    from app.main import app

    with patch("app.auth.get_auth_store", return_value=store), patch("app.auth.TenantConnection") as tc:
        tc.return_value.connect.return_value = MagicMock()
        yield TestClient(app, raise_server_exceptions=False)


def rpc(client: TestClient, method: str, params: dict | None = None, req_id=1, headers: dict | None = None):
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return client.post("/mcp", json=msg, headers=headers if headers is not None else _HEADERS)


def call_tool(client: TestClient, name: str, arguments: dict | None = None):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})


def tool_text(resp) -> dict:
    """Decode the JSON inside the first text content block of a tool result."""
    result = resp.json()["result"]
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class TestTransport:
    def test_missing_auth_returns_401(self, client: TestClient):
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth_missing"

    def test_get_returns_405(self, client: TestClient):
        resp = client.get("/mcp")
        assert resp.status_code == 405
        assert resp.json()["error"]["code"] == "method_not_allowed"
        assert resp.headers["allow"] == "POST"

    def test_delete_returns_405(self, client: TestClient):
        resp = client.delete("/mcp")
        assert resp.status_code == 405

    def test_parse_error(self, client: TestClient):
        resp = client.post("/mcp", content=b"{nope", headers={**_HEADERS, "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32700
        assert body["id"] is None

    def test_batch_rejected(self, client: TestClient):
        resp = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=_HEADERS)
        assert resp.json()["error"]["code"] == -32600

    def test_wrong_jsonrpc_version(self, client: TestClient):
        resp = client.post("/mcp", json={"jsonrpc": "1.0", "id": 1, "method": "ping"}, headers=_HEADERS)
        assert resp.json()["error"]["code"] == -32600

    def test_notification_returns_202(self, client: TestClient):
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=_HEADERS)
        assert resp.status_code == 202
        assert resp.content == b""

    def test_unknown_method(self, client: TestClient):
        resp = rpc(client, "resources/list")
        assert resp.json()["error"]["code"] == -32601

    def test_response_is_single_json_object(self, client: TestClient):
        resp = rpc(client, "ping")
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert body["result"] == {}


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_foreign_origin_rejected(self, client: TestClient):
        resp = rpc(client, "ping", headers={**_HEADERS, "Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "origin_forbidden"

    def test_localhost_origin_allowed(self, client: TestClient):
        resp = rpc(client, "ping", headers={**_HEADERS, "Origin": "http://localhost:3000"})
        assert resp.status_code == 200

    def test_same_host_origin_allowed(self, client: TestClient):
        # TestClient requests carry Host: testserver
        resp = rpc(client, "ping", headers={**_HEADERS, "Origin": "http://testserver"})
        assert resp.status_code == 200

    def test_unsupported_protocol_version_header(self, client: TestClient):
        resp = rpc(client, "ping", headers={**_HEADERS, "MCP-Protocol-Version": "2024-11-05"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "unsupported_protocol_version"

    def test_supported_protocol_version_header(self, client: TestClient):
        resp = rpc(client, "ping", headers={**_HEADERS, "MCP-Protocol-Version": "2025-06-18"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Lifecycle methods
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_echoes_supported_version(self, client: TestClient):
        resp = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
        result = resp.json()["result"]
        assert result["protocolVersion"] == "2025-03-26"

    def test_falls_back_for_unknown_version(self, client: TestClient):
        resp = rpc(client, "initialize", {"protocolVersion": "1999-01-01"})
        assert resp.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_falls_back_for_missing_version(self, client: TestClient):
        resp = rpc(client, "initialize")
        assert resp.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_capabilities_and_server_info(self, client: TestClient):
        result = rpc(client, "initialize").json()["result"]
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == "maludb"
        assert result["serverInfo"]["title"] == "MaluDB Memory"


class TestToolsList:
    def test_lists_all_nine_tools(self, client: TestClient):
        result = rpc(client, "tools/list").json()["result"]
        names = {t["name"] for t in result["tools"]}
        assert names == _READ_TOOLS | _WRITE_TOOLS
        assert "nextCursor" not in result

    def test_cursor_is_ignored(self, client: TestClient):
        result = rpc(client, "tools/list", {"cursor": "abc"}).json()["result"]
        assert len(result["tools"]) == 9

    def test_tool_shapes(self, client: TestClient):
        for tool in rpc(client, "tools/list").json()["result"]["tools"]:
            assert tool["description"]
            assert tool["inputSchema"]["type"] == "object"
            expected_read_only = tool["name"] in _READ_TOOLS
            assert tool["annotations"]["readOnlyHint"] is expected_read_only, tool["name"]
            assert tool["annotations"]["destructiveHint"] is False

    def test_registry_is_plain_data(self):
        # The registry is a cross-server contract — must be JSON-serializable as-is.
        assert json.loads(json.dumps(TOOLS)) == TOOLS


# ---------------------------------------------------------------------------
# tools/call — protocol-level validation
# ---------------------------------------------------------------------------


class TestToolsCallValidation:
    def test_unknown_tool(self, client: TestClient):
        resp = call_tool(client, "drop_database")
        assert resp.json()["error"]["code"] == -32602

    def test_missing_required_argument(self, client: TestClient):
        resp = call_tool(client, "store_memory", {})
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert '"text"' in body["error"]["message"]

    def test_get_skill_requires_id_or_name(self, client: TestClient):
        resp = call_tool(client, "get_skill", {})
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert "skill_id" in body["error"]["message"]

    def test_non_numeric_limit_is_invalid_params(self, client: TestClient):
        resp = call_tool(client, "find_subjects", {"limit": "lots"})
        body = resp.json()
        assert body["error"]["code"] == -32602
        assert '"limit"' in body["error"]["message"]


# ---------------------------------------------------------------------------
# tools/call — handlers (db helpers / cores patched)
# ---------------------------------------------------------------------------


class TestToolsCallHandlers:
    def test_find_subjects_round_trip(self, client: TestClient):
        rows = [{"id": 1, "name": "Edward", "type": "person", "description": None}]
        with patch("app.routers.mcp.db_query", return_value=rows) as q:
            resp = call_tool(client, "find_subjects", {"query": "ed", "limit": 5})
        result = resp.json()["result"]
        assert "isError" not in result
        assert tool_text(resp)["subjects"][0]["name"] == "Edward"
        # limit is passed through as the last SQL param
        assert q.call_args[0][2][-1] == 5

    def test_get_document_found(self, client: TestClient):
        doc = {
            "id": 7,
            "title": "T",
            "source_type": "document",
            "media_type": None,
            "document_type": None,
            "primary_project_id": None,
            "description": None,
            "content_size": 10,
            "content_hash": "x",
            "created_at": None,
            "updated_at": None,
        }
        with (
            patch("app.routers.mcp.db_one", return_value=dict(doc)),
            patch("app.routers.mcp.db_query", return_value=[]),
        ):
            resp = call_tool(client, "get_document", {"document_id": 7})
        assert tool_text(resp)["document"]["id"] == 7

    def test_get_document_not_found_is_error(self, client: TestClient):
        with patch("app.routers.mcp.db_one", return_value=None):
            resp = call_tool(client, "get_document", {"document_id": 999})
        result = resp.json()["result"]
        assert result["isError"] is True
        assert tool_text(resp)["error"]["code"] == "not_found"

    def test_search_memory_missing_prefilter_suggests_subjects(self, client: TestClient):
        rows = [{"name": "Edward", "type": "person"}]
        with patch("app.routers.mcp.db_query", return_value=rows), patch("app.routers.mcp.search_core") as core:
            resp = call_tool(client, "search_memory", {"query": "edward oracle upgrade"})
        result = resp.json()["result"]
        assert result["isError"] is True
        err = tool_text(resp)["error"]
        assert err["code"] == "missing_field"
        assert "Edward" in err["message"]
        assert "find_subjects" in err["message"]
        core.assert_not_called()

    def test_search_memory_delegates_to_core(self, client: TestClient):
        canned = {"namespace": "default", "embedding_model": "m", "results": []}
        with patch("app.routers.mcp.search_core", return_value=canned) as core:
            resp = call_tool(client, "search_memory", {"query": "x", "subject": "Edward", "limit": 999})
        assert tool_text(resp) == canned
        assert core.call_args.kwargs["limit"] == 50  # clamped to the schema max
        assert core.call_args.kwargs["subject"] == "Edward"

    def test_store_memory_api_error_becomes_is_error(self, client: TestClient):
        with patch("app.routers.mcp.ingest_core", side_effect=APIError("model_not_configured", "no model", 422)):
            resp = call_tool(client, "store_memory", {"text": "remember this"})
        result = resp.json()["result"]
        assert result["isError"] is True
        assert tool_text(resp)["error"]["code"] == "model_not_configured"

    def test_store_document_delegates_to_core(self, client: TestClient):
        canned = {
            "document_id": 3,
            "namespace": "default",
            "embedding_model": "m",
            "extractor": "llm",
            "chunk_count": 1,
            "edges": [],
        }
        with patch("app.routers.mcp.documents_core", return_value=canned) as core:
            resp = call_tool(client, "store_document", {"title": "T", "text": "body", "subjects": ["Edward"]})
        assert tool_text(resp)["document_id"] == 3
        assert core.call_args.kwargs["subjects"] == ["Edward"]
        assert core.call_args.kwargs["provided_edges"] is None

    def test_explore_subject_ambiguous_is_error(self, client: TestClient):
        candidates = [
            {"id": 1, "name": "Oracle Database 21c", "type": "software"},
            {"id": 2, "name": "Oracle Cloud", "type": "software"},
        ]
        with (
            patch("app.routers.mcp.db_one", return_value=None),
            patch("app.routers.mcp.db_query", return_value=candidates),
        ):
            resp = call_tool(client, "explore_subject", {"subject": "Oracle"})
        result = resp.json()["result"]
        assert result["isError"] is True
        err = tool_text(resp)["error"]
        assert err["code"] == "ambiguous_subject"
        assert "Oracle Cloud" in err["message"]

    def test_explore_subject_neighbors(self, client: TestClient):
        subject_row = {"id": 5, "name": "Edward", "type": "person"}
        neighbors = [
            {
                "neighbor_kind": "subject",
                "neighbor_id": 9,
                "rel": "perform",
                "edge_store": "svo",
                "confidence": None,
                "provenance": "suggested",
                "label": "upgrade",
            }
        ]
        with (
            patch("app.routers.mcp.db_one", return_value=dict(subject_row)),
            patch("app.routers.mcp.db_tx_core", return_value=neighbors),
        ):
            resp = call_tool(client, "explore_subject", {"subject": "Edward"})
        payload = tool_text(resp)
        assert payload["subject"]["name"] == "Edward"
        assert payload["neighbors"][0]["neighbor_id"] == 9

    def test_explore_subject_bad_direction(self, client: TestClient):
        with patch("app.routers.mcp.db_one", return_value={"id": 1, "name": "E", "type": "person"}):
            resp = call_tool(client, "explore_subject", {"subject": "1", "direction": "sideways"})
        assert resp.json()["error"]["code"] == -32602

    def test_get_skill_by_name_not_found(self, client: TestClient):
        with patch("app.routers.mcp.db_one", return_value=None):
            resp = call_tool(client, "get_skill", {"name": "no-such-skill"})
        assert tool_text(resp)["error"]["code"] == "not_found"
        assert resp.json()["result"]["isError"] is True
