"""
End-to-end tests for the generic user-table API against a REAL tenant database.

Skipped unless both env vars are set:

    MALUDB_E2E_TOKEN  a malu_ API token resolvable by the local auth store
    MALUDB_E2E_DSN    a psycopg DSN for the SAME tenant DB/user the token maps
                      to (used only to CREATE/DROP the scratch table)

Example (local dev):

    MALUDB_E2E_TOKEN=malu_… \
    MALUDB_E2E_DSN='host=127.0.0.1 dbname=maludb user=app password=…' \
    pytest tests/test_rest_e2e.py -v

The suite creates a scratch table in the tenant schema, exercises both mounts
through the full app (real auth resolution, real Postgres), and drops it.
"""

from __future__ import annotations

import os

import pytest

TOKEN = os.environ.get("MALUDB_E2E_TOKEN")
DSN = os.environ.get("MALUDB_E2E_DSN")

pytestmark = pytest.mark.skipif(
    not (TOKEN and DSN),
    reason="e2e disabled — set MALUDB_E2E_TOKEN and MALUDB_E2E_DSN",
)

TABLE = "e2e_scratch_todos"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


@pytest.fixture(scope="module", autouse=True)
def scratch_table():
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
        conn.execute(
            f'CREATE TABLE "{TABLE}" ('
            "  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "  title text NOT NULL,"
            "  done boolean NOT NULL DEFAULT false,"
            "  meta jsonb,"
            "  tags text[],"
            '  "dueAt" timestamptz,'
            "  amount numeric(30, 10),"
            "  blob bytea,"
            "  UNIQUE (title))"
        )
    yield
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{TABLE}"')


REPR = {"Prefer": "return=representation"}


class TestRestFlavorE2E:
    def test_insert_bulk_representation(self, client):
        r = client.post(
            f"/rest/v1/{TABLE}",
            json=[
                {"title": "walk dog", "meta": {"tags": ["pets"]}},
                {"title": "write docs", "done": True},
                {"title": "ship it"},
            ],
            headers=REPR,
        )
        assert r.status_code == 201, r.text
        rows = r.json()
        assert [row["title"] for row in rows] == ["walk dog", "write docs", "ship it"]
        assert rows[0]["meta"] == {"tags": ["pets"]}

    def test_filter_select_order(self, client):
        r = client.get(f"/rest/v1/{TABLE}?done=is.false&select=title&order=title.desc")
        assert r.status_code == 200
        assert r.json() == [{"title": "walk dog"}, {"title": "ship it"}]

    def test_count_and_content_range(self, client):
        r = client.get(f"/rest/v1/{TABLE}?limit=1", headers={"Prefer": "count=exact"})
        assert r.status_code == 200
        assert r.headers["content-range"] == "0-0/3"

    def test_single_object_accept(self, client):
        headers = {"Accept": "application/vnd.pgrst.object+json"}
        r = client.get(f"/rest/v1/{TABLE}?title=eq.ship it", headers=headers)
        assert r.status_code == 200
        assert r.json()["title"] == "ship it"

        r = client.get(f"/rest/v1/{TABLE}", headers=headers)  # 3 rows → 406
        assert r.status_code == 406
        assert r.json()["code"] == "PGRST116"

    def test_upsert_merge(self, client):
        r = client.post(
            f"/rest/v1/{TABLE}?on_conflict=title",
            json={"title": "ship it", "done": True},
            headers={"Prefer": "return=representation, resolution=merge-duplicates"},
        )
        assert r.status_code == 201, r.text
        assert r.json()[0]["done"] is True

    def test_patch_filtered(self, client):
        r = client.patch(f"/rest/v1/{TABLE}?title=eq.walk dog", json={"done": True}, headers=REPR)
        assert r.status_code == 200
        assert r.json()[0]["done"] is True

    def test_patch_minimal_is_204(self, client):
        r = client.patch(f"/rest/v1/{TABLE}?title=eq.walk dog", json={"done": True})
        assert r.status_code == 204
        assert r.content == b""

    def test_unknown_filter_key_rejected(self, client):
        r = client.delete(f"/rest/v1/{TABLE}?idd=eq.1")
        assert r.status_code == 400
        assert r.json()["code"] == "PGRST204"

    def test_db_error_shape(self, client):
        r = client.post(f"/rest/v1/{TABLE}", json={"title": "ship it"})  # unique violation
        assert r.status_code == 409
        body = r.json()
        assert body["code"] == "23505"
        assert "duplicate key" in body["message"]

    def test_memory_facades_not_served(self, client):
        r = client.get("/rest/v1/maludb_subject")
        assert r.status_code == 404
        assert r.json()["code"] == "PGRST205"

    def test_delete_filtered(self, client):
        r = client.delete(f"/rest/v1/{TABLE}?title=eq.write docs", headers=REPR)
        assert r.status_code == 200
        assert r.json()[0]["title"] == "write docs"

    # -- regression tests for the 2026-07-01 review findings ---------------

    def test_array_column_roundtrip(self, client):
        r = client.post(f"/rest/v1/{TABLE}", json={"title": "arrayed", "tags": ["a", "b"]}, headers=REPR)
        assert r.status_code == 201, r.text
        assert r.json()[0]["tags"] == ["a", "b"]
        client.delete(f"/rest/v1/{TABLE}?title=eq.arrayed")

    def test_camelcase_column_key_preserved(self, client):
        r = client.post(
            f"/rest/v1/{TABLE}",
            json={"title": "cased", "dueAt": "2026-07-01T12:00:00Z"},
            headers=REPR,
        )
        assert r.status_code == 201, r.text
        assert "dueAt" in r.json()[0], r.json()[0]
        r = client.get(f"/rest/v1/{TABLE}?title=eq.cased&select=*")
        assert "dueAt" in r.json()[0]
        client.delete(f"/rest/v1/{TABLE}?title=eq.cased")

    def test_numeric_precision_filter(self, client):
        big = "12345678901234567890.5"
        client.post(f"/rest/v1/{TABLE}", json={"title": "precise", "amount": big})
        r = client.get(f"/rest/v1/{TABLE}?amount=eq.{big}&select=title")
        assert r.json() == [{"title": "precise"}]
        client.delete(f"/rest/v1/{TABLE}?title=eq.precise")

    def test_limited_delete_windows(self, client):
        client.post(
            f"/rest/v1/{TABLE}",
            json=[{"title": "win 1"}, {"title": "win 2"}, {"title": "win 3"}],
        )
        r = client.delete(f"/rest/v1/{TABLE}?title=like.win *&order=title&limit=1", headers=REPR)
        assert [x["title"] for x in r.json()] == ["win 1"]
        r = client.get(f"/rest/v1/{TABLE}?title=like.win *&select=title&order=title")
        assert [x["title"] for x in r.json()] == ["win 2", "win 3"]
        client.delete(f"/rest/v1/{TABLE}?title=like.win *")

    def test_single_write_mismatch_rolls_back(self, client):
        r = client.post(
            f"/rest/v1/{TABLE}",
            json=[{"title": "tx 1"}, {"title": "tx 2"}],
            headers={
                "Prefer": "return=representation",
                "Accept": "application/vnd.pgrst.object+json",
            },
        )
        assert r.status_code == 406
        r = client.get(f"/rest/v1/{TABLE}?title=like.tx *")
        assert r.json() == []  # nothing persisted — the 406 rolled the insert back

    def test_malformed_json_is_400(self, client):
        r = client.post(f"/rest/v1/{TABLE}", content='{"title": ', headers={"content-type": "application/json"})
        assert r.status_code == 400
        assert r.json()["code"] == "PGRST102"

    def test_post_rejects_filter_params(self, client):
        r = client.post(f"/rest/v1/{TABLE}?id=eq.5", json={"title": "nope"})
        assert r.status_code == 400
        r = client.get(f"/rest/v1/{TABLE}?title=eq.nope")
        assert r.json() == []

    def test_offset_only_delete_not_capped(self, client, scratch_table):
        """Offset-only writes must not inherit the default LIMIT 1000."""
        import psycopg

        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(f"INSERT INTO \"{TABLE}\" (title) SELECT 'cap ' || n FROM generate_series(1, 1500) n")
        r = client.delete(f"/rest/v1/{TABLE}?title=like.cap *&order=id&offset=0")
        assert r.status_code == 204
        r = client.get(f"/rest/v1/{TABLE}?title=like.cap *", headers={"Prefer": "count=exact"})
        assert r.headers["content-range"].endswith("/0")  # all 1500 gone, not 500 left

    def test_bytea_read_is_hex(self, client):
        import psycopg

        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                f"INSERT INTO \"{TABLE}\" (title, blob) VALUES ('binary', %s)",
                [b"\x89PNG\xff"],
            )
        r = client.get(f"/rest/v1/{TABLE}?title=eq.binary&select=blob")
        assert r.status_code == 200
        assert r.json() == [{"blob": "\\x89504e47ff"}]
        client.delete(f"/rest/v1/{TABLE}?title=eq.binary")

    def test_over_max_limit_clamps(self, client):
        r = client.get(f"/rest/v1/{TABLE}?limit=2000")
        assert r.status_code == 200  # Supabase max-rows behavior: clamp, not 422

    def test_debug_filter_shape_rejected(self, client):
        r = client.delete(f"/rest/v1/{TABLE}?debug=eq.true")
        assert r.status_code == 400

    def test_in_list_with_quoted_values(self, client):
        client.post(f"/rest/v1/{TABLE}", json=[{"title": "q,1"}, {"title": "q2"}])
        r = client.get(f'/rest/v1/{TABLE}?title=in.("q,1",q2)&select=title&order=title')
        assert [x["title"] for x in r.json()] == ["q,1", "q2"]
        client.delete(f'/rest/v1/{TABLE}?title=in.("q,1",q2)')

    def test_unsupported_operator_is_400_not_silent(self, client):
        r = client.delete(f"/rest/v1/{TABLE}?tags=cs.{{a}}")
        assert r.status_code == 400
        assert "operator" in r.json()["message"].lower()

    def test_head_with_object_accept_is_not_406(self, client):
        """HEAD + .single() Accept must return headers, not a cardinality 406
        computed from the deliberately empty HEAD body."""
        r = client.head(
            f"/rest/v1/{TABLE}?title=eq.ship it",
            headers={"Accept": "application/vnd.pgrst.object+json"},
        )
        assert r.status_code == 200

    def test_head_count_without_body(self, client):
        client.post(f"/rest/v1/{TABLE}", json=[{"title": "hd 1"}, {"title": "hd 2"}, {"title": "hd 3"}])
        r = client.head(f"/rest/v1/{TABLE}?title=like.hd *&limit=1", headers={"Prefer": "count=exact"})
        assert r.status_code == 200
        assert r.headers["content-range"] == "0-0/3"  # 1 returned of 3 total
        client.delete(f"/rest/v1/{TABLE}?title=like.hd *")

    def test_percent_column_name_works(self, client):
        import psycopg

        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS e2e_pct")
            conn.execute('CREATE TABLE e2e_pct (id int PRIMARY KEY, "growth%" int)')
        try:
            r = client.post("/rest/v1/e2e_pct", json={"id": 1, "growth%": 42}, headers=REPR)
            assert r.status_code == 201, r.text
            assert r.json()[0]["growth%"] == 42
            r = client.get("/rest/v1/e2e_pct?select=*")
            assert r.json() == [{"id": 1, "growth%": 42}]
        finally:
            with psycopg.connect(DSN, autocommit=True) as conn:
                conn.execute("DROP TABLE e2e_pct")

    def test_heterogeneous_merge_upsert_rejected(self, client):
        r = client.post(
            f"/rest/v1/{TABLE}?on_conflict=title",
            json=[{"title": "h1", "done": True}, {"title": "h2"}],
            headers={"Prefer": "resolution=merge-duplicates"},
        )
        assert r.status_code == 400
        assert "keys must match" in r.json()["message"]


class TestTablesFlavorE2E:
    def test_envelopes_and_house_errors(self, client):
        r = client.get(f"/v1/tables/{TABLE}?select=title&order=title")
        assert r.status_code == 200
        assert "rows" in r.json()

        r = client.post(f"/v1/tables/{TABLE}", json={"title": "house row"})
        assert r.status_code == 201
        assert r.json() == {"inserted": 1}

        r = client.patch(f"/v1/tables/{TABLE}?title=eq.house row", json={"done": True})
        assert r.json() == {"updated": 1}

        r = client.delete(f"/v1/tables/{TABLE}?title=eq.house row")
        assert r.json() == {"deleted": 1}

        r = client.get("/v1/tables/nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "table_not_found"
