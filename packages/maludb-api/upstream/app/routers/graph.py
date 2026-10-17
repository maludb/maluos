"""
Graph endpoints — edges, neighbors, walk, path, stats.

Ports PHP's edges.php, graph_neighbors.php, and graph_walk.php.

- GET /v1/edges        — unified edge view over maludb_edge
- GET /v1/graph/neighbors — one-hop neighbors via maludb_graph_neighbors()
- GET /v1/graph/walk      — multi-hop BFS via maludb_graph_walk()
- GET /v1/graph/path      — source→target paths via maludb_graph_path() (core ≥0.101.0)
- GET /v1/graph/stats     — node/edge/rel/store aggregates over maludb_edge
- GET /v1/graph/god-nodes — highest-degree nodes via maludb_graph_degree() (core ≥0.102.0)
- GET /v1/graph/surprises — cross-community edges via maludb_graph_surprises() (core ≥0.102.0)
- GET /v1/communities     — namespace community sets (core ≥0.102.0)
- GET /v1/communities/{id}/members — community membership with labels

All queries run inside db_tx_core() so the maludb_core facade views resolve.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Query, Request

from app.auth import Auth
from app.database import db_query, db_tx_core
from app.errors import json_error

router = APIRouter()

_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# Graphify tags every extracted relationship EXTRACTED / INFERRED /
# AMBIGUOUS; SVO statements store numeric confidence. The mapping is
# reversible (three distinct values).
_CONFIDENCE_MAP = {"EXTRACTED": 1.0, "INFERRED": 0.7, "AMBIGUOUS": 0.4}

_MAX_NODES = 50_000
_MAX_LINKS = 200_000
_MAX_SKIPPED_REPORTED = 200


# ===========================================================================
# GET /v1/edges — unified edge view
# ===========================================================================


@router.get("/v1/edges")
def list_edges(
    auth: Auth,
    source_kind: str | None = Query(default=None, max_length=40),
    source_id: int | None = Query(default=None),
    target_kind: str | None = Query(default=None, max_length=40),
    target_id: int | None = Query(default=None),
    rel: str | None = Query(default=None, max_length=120),
    edge_store: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, le=500),
):
    def _query(conn):
        clauses: list[str] = []
        params: list = []
        if source_kind:
            clauses.append("source_kind = %s")
            params.append(source_kind)
        if source_id is not None:
            clauses.append("source_id = %s")
            params.append(source_id)
        if target_kind:
            clauses.append("target_kind = %s")
            params.append(target_kind)
        if target_id is not None:
            clauses.append("target_id = %s")
            params.append(target_id)
        if rel:
            clauses.append("rel = %s")
            params.append(rel)
        if edge_store:
            clauses.append("edge_store = %s")
            params.append(edge_store)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        sql = f"""SELECT edge_store, edge_id, source_kind, source_id, rel,
                         target_kind, target_id, confidence, provenance
                    FROM maludb_edge
                    {where}
                   ORDER BY edge_store, edge_id DESC
                   LIMIT %s"""
        params.append(limit)

        rows = db_query(conn, sql, params)
        for r in rows:
            r["edge_id"] = int(r["edge_id"]) if r["edge_id"] is not None else None
            r["source_id"] = int(r["source_id"])
            r["target_id"] = int(r["target_id"])
            r["confidence"] = float(r["confidence"]) if r["confidence"] is not None else None
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"edges": rows}


# ===========================================================================
# GET /v1/graph/neighbors — one-hop neighbors
# ===========================================================================


@router.get("/v1/graph/neighbors")
def graph_neighbors(
    auth: Auth,
    kind: str = Query(max_length=40),
    id: int = Query(),
    direction: str = Query(default="both", max_length=20),
    rel: str | None = Query(default=None, max_length=400),
):
    if not kind:
        json_error("missing_field", 'Query param "kind" is required.', 400)

    def _query(conn):
        if rel:
            rel_list = [r.strip() for r in rel.split(",") if r.strip()]
            sql = """SELECT neighbor_kind, neighbor_id, rel, edge_store,
                            confidence, provenance, label
                       FROM maludb_graph_neighbors(%s, %s, %s, %s::text[])"""
            params = [kind, id, direction, rel_list]
        else:
            sql = """SELECT neighbor_kind, neighbor_id, rel, edge_store,
                            confidence, provenance, label
                       FROM maludb_graph_neighbors(%s, %s, %s)"""
            params = [kind, id, direction]

        rows = db_query(conn, sql, params)
        for r in rows:
            r["neighbor_id"] = int(r["neighbor_id"])
            r["confidence"] = float(r["confidence"]) if r["confidence"] is not None else None
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"kind": kind, "id": id, "direction": direction, "neighbors": rows}


# ===========================================================================
# GET /v1/graph/walk — multi-hop BFS
# ===========================================================================


@router.get("/v1/graph/walk")
def graph_walk(
    auth: Auth,
    kind: str = Query(max_length=40),
    id: int = Query(),
    max_depth: int = Query(default=4, le=20),
    direction: str = Query(default="both", max_length=20),
    rel: str | None = Query(default=None, max_length=400),
):
    if not kind:
        json_error("missing_field", 'Query param "kind" is required.', 400)

    def _query(conn):
        if rel:
            rel_list = [r.strip() for r in rel.split(",") if r.strip()]
            sql = """SELECT object_kind, object_id, depth, rel, edge_store, label, path
                       FROM maludb_graph_walk(%s, %s, %s, %s, %s::text[])"""
            params = [kind, id, max_depth, direction, rel_list]
        else:
            sql = """SELECT object_kind, object_id, depth, rel, edge_store, label, path
                       FROM maludb_graph_walk(%s, %s, %s, %s)"""
            params = [kind, id, max_depth, direction]

        rows = db_query(conn, sql, params)
        for r in rows:
            r["object_id"] = int(r["object_id"])
            r["depth"] = int(r["depth"])
            # psycopg v3 auto-converts Postgres text[] to Python list;
            # ensure None/empty becomes [].
            if r["path"] is None:
                r["path"] = []
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {
        "kind": kind,
        "id": id,
        "max_depth": max_depth,
        "direction": direction,
        "walk": rows,
    }


# ===========================================================================
# GET /v1/graph/path — source→target paths, shortest first
# ===========================================================================


@router.get("/v1/graph/path")
def graph_path(
    auth: Auth,
    source_kind: str = Query(max_length=40),
    source_id: int = Query(),
    target_kind: str = Query(max_length=40),
    target_id: int = Query(),
    max_depth: int = Query(default=6, ge=1, le=32),
    direction: str = Query(default="both", max_length=20),
    rel: str | None = Query(default=None, max_length=400),
):
    if not source_kind:
        json_error("missing_field", 'Query param "source_kind" is required.', 400)
    if not target_kind:
        json_error("missing_field", 'Query param "target_kind" is required.', 400)

    def _query(conn):
        if rel:
            rel_list = [r.strip() for r in rel.split(",") if r.strip()]
            sql = """SELECT depth, path
                       FROM maludb_graph_path(%s, %s, %s, %s, %s, %s, %s::text[])"""
            params = [source_kind, source_id, target_kind, target_id, max_depth, direction, rel_list]
        else:
            sql = """SELECT depth, path
                       FROM maludb_graph_path(%s, %s, %s, %s, %s, %s)"""
            params = [source_kind, source_id, target_kind, target_id, max_depth, direction]

        rows = db_query(conn, sql, params)
        for r in rows:
            r["depth"] = int(r["depth"])
            if r["path"] is None:
                r["path"] = []
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        "target_kind": target_kind,
        "target_id": target_id,
        "max_depth": max_depth,
        "direction": direction,
        "paths": rows,
    }


# ===========================================================================
# GET /v1/graph/stats — aggregates over the unified edge view
# ===========================================================================


@router.get("/v1/graph/stats")
def graph_stats(
    auth: Auth,
    top_rels: int = Query(default=25, ge=1, le=100),
):
    def _query(conn):
        totals = db_query(
            conn,
            "SELECT count(*) AS edges FROM maludb_edge",
        )[0]

        nodes = db_query(
            conn,
            """SELECT count(*) AS nodes
                 FROM (SELECT source_kind AS kind, source_id AS id FROM maludb_edge
                       UNION
                       SELECT target_kind, target_id FROM maludb_edge) endpoints""",
        )[0]

        by_store = db_query(
            conn,
            """SELECT edge_store, count(*) AS edges
                 FROM maludb_edge
                GROUP BY edge_store
                ORDER BY edges DESC, edge_store""",
        )

        by_rel = db_query(
            conn,
            """SELECT rel, count(*) AS edges
                 FROM maludb_edge
                GROUP BY rel
                ORDER BY edges DESC, rel NULLS LAST
                LIMIT %s""",
            [top_rels],
        )

        return {
            "edges": int(totals["edges"]),
            "nodes": int(nodes["nodes"]),
            "by_store": {r["edge_store"]: int(r["edges"]) for r in by_store},
            "top_rels": [
                {"rel": r["rel"], "edges": int(r["edges"])} for r in by_rel
            ],
        }

    stats = db_tx_core(auth.conn, _query)
    return {"stats": stats}


# ===========================================================================
# GET /v1/graph/query — lexical seed + bounded walk (graphify-style query)
# ===========================================================================


@router.get("/v1/graph/query")
def graph_query(
    auth: Auth,
    q: str = Query(min_length=1, max_length=400),
    namespace: str | None = Query(default=None, max_length=64),
    depth: int = Query(default=2, ge=1, le=6),
    seeds: int = Query(default=3, ge=1, le=10),
    max_nodes: int = Query(default=50, ge=1, le=500),
):
    """
    Graphify-style graph question answering: tokenize the question, score
    subjects by how many terms match their canonical name or aliases, walk
    the unified graph from the top-scoring seeds, and return the merged
    subgraph (nodes + the edges among them).
    """
    terms = [t for t in re.split(r"[^a-z0-9_]+", q.lower()) if len(t) >= 2]
    if not terms:
        json_error("validation_failed", 'Query param "q" has no searchable terms.', 422)
    terms = terms[:12]

    def _query(conn):
        # ---- seed scoring: one point per matching term -------------------
        score_expr = " + ".join(
            "(CASE WHEN canonical_name ILIKE %s OR array_to_string(aliases, ' ') ILIKE %s THEN 1 ELSE 0 END)"
            for _ in terms
        )
        params: list = []
        for t in terms:
            like = f"%{t}%"
            params.extend([like, like])
        ns_clause = ""
        if namespace:
            ns_clause = "AND (canonical_name LIKE %s OR canonical_name = %s)"
            params.extend([f"{namespace}/%", namespace])
        params.append(seeds)

        like_params = params[: len(terms) * 2]
        tail_params = params[len(terms) * 2 :]
        seed_rows = db_query(
            conn,
            f"""SELECT subject_id, canonical_name, aliases, ({score_expr}) AS score
                  FROM maludb_subject
                 WHERE ({score_expr}) > 0
                   {ns_clause}
                 ORDER BY score DESC, subject_id
                 LIMIT %s""",
            like_params + like_params + tail_params,
        )
        if not seed_rows:
            return {"seeds": [], "nodes": [], "edges": []}

        # ---- walk from each seed, merge shallowest-depth-wins -------------
        node_depth: dict[tuple[str, int], dict] = {}
        for s in seed_rows:
            sid = int(s["subject_id"])
            node_depth.setdefault(("subject", sid), {
                "object_kind": "subject",
                "object_id": sid,
                "label": (s["aliases"] or [s["canonical_name"]])[0],
                "canonical_name": s["canonical_name"],
                "depth": 0,
            })
            walk = db_query(
                conn,
                """SELECT object_kind, object_id, depth, label
                     FROM maludb_graph_walk(%s, %s, %s, 'both')""",
                ["subject", sid, depth],
            )
            for w in walk:
                key = (w["object_kind"], int(w["object_id"]))
                d = int(w["depth"])
                if key not in node_depth or d < node_depth[key]["depth"]:
                    node_depth[key] = {
                        "object_kind": w["object_kind"],
                        "object_id": int(w["object_id"]),
                        "label": w["label"],
                        "depth": d,
                    }

        nodes = sorted(node_depth.values(), key=lambda n: (n["depth"], n["object_id"]))[:max_nodes]
        kept = {(n["object_kind"], n["object_id"]) for n in nodes}

        # ---- edges among kept nodes (coarse id prefilter, exact kind+id
        # check in Python since ids are only unique per kind) ---------------
        kept_ids = sorted({n["object_id"] for n in nodes})
        edge_rows = db_query(
            conn,
            """SELECT source_kind, source_id, rel, target_kind, target_id, confidence
                 FROM maludb_edge
                WHERE source_id = ANY(%s) AND target_id = ANY(%s)""",
            [kept_ids, kept_ids],
        )
        edges = [
            {
                "source_kind": e["source_kind"],
                "source_id": int(e["source_id"]),
                "rel": e["rel"],
                "target_kind": e["target_kind"],
                "target_id": int(e["target_id"]),
                "confidence": float(e["confidence"]) if e["confidence"] is not None else None,
            }
            for e in edge_rows
            if (e["source_kind"], int(e["source_id"])) in kept
            and (e["target_kind"], int(e["target_id"])) in kept
        ]

        return {
            "seeds": [
                {
                    "subject_id": int(s["subject_id"]),
                    "canonical_name": s["canonical_name"],
                    "score": int(s["score"]),
                }
                for s in seed_rows
            ],
            "nodes": nodes,
            "edges": edges,
        }

    result = db_tx_core(auth.conn, _query)
    return {"query": q, "namespace": namespace, "depth": depth, **result}


# ===========================================================================
# GET /v1/graph/god-nodes — highest-degree nodes
# ===========================================================================


@router.get("/v1/graph/god-nodes")
def graph_god_nodes(
    auth: Auth,
    limit: int = Query(default=10, ge=1, le=1000),
):
    def _query(conn):
        rows = db_query(
            conn,
            """SELECT object_kind, object_id, label, degree_out, degree_in, degree_total
                 FROM maludb_graph_degree(%s)""",
            [limit],
        )
        for r in rows:
            r["object_id"] = int(r["object_id"])
            for k in ("degree_out", "degree_in", "degree_total"):
                r[k] = int(r[k])
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"limit": limit, "god_nodes": rows}


# ===========================================================================
# GET /v1/graph/surprises — cross-community edges, rarest pair first
# ===========================================================================


@router.get("/v1/graph/surprises")
def graph_surprises(
    auth: Auth,
    namespace: str = Query(max_length=64),
    limit: int = Query(default=25, ge=1, le=200),
):
    if not namespace:
        json_error("missing_field", 'Query param "namespace" is required.', 400)

    def _query(conn):
        rows = db_query(
            conn,
            """SELECT source_kind, source_id, source_label, source_community,
                      rel, target_kind, target_id, target_label, target_community,
                      community_pair_edges
                 FROM maludb_graph_surprises(%s, %s)""",
            [namespace, limit],
        )
        for r in rows:
            for k in ("source_id", "target_id", "source_community", "target_community", "community_pair_edges"):
                r[k] = int(r[k])
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"namespace": namespace, "limit": limit, "surprises": rows}


# ===========================================================================
# GET /v1/communities — community sets with sizes
# ===========================================================================


@router.get("/v1/communities")
def list_communities(
    auth: Auth,
    namespace: str | None = Query(default=None, max_length=64),
):
    def _query(conn):
        clauses = ""
        params: list = []
        if namespace:
            clauses = "WHERE c.namespace = %s"
            params.append(namespace)
        rows = db_query(
            conn,
            f"""SELECT c.community_id, c.namespace, c.community_key, c.label,
                       c.algorithm, c.computed_at, count(m.membership_id) AS member_count
                  FROM maludb_community c
                  LEFT JOIN maludb_community_membership m ON m.community_id = c.community_id
                  {clauses}
                 GROUP BY c.community_id, c.namespace, c.community_key, c.label,
                          c.algorithm, c.computed_at
                 ORDER BY c.namespace, c.community_key""",
            params,
        )
        for r in rows:
            r["community_id"] = int(r["community_id"])
            r["community_key"] = int(r["community_key"])
            r["member_count"] = int(r["member_count"])
            r["computed_at"] = r["computed_at"].isoformat()
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"communities": rows}


# ===========================================================================
# GET /v1/communities/{community_id}/members
# ===========================================================================


@router.get("/v1/communities/{community_id}/members")
def community_members(
    auth: Auth,
    community_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
):
    def _query(conn):
        exists = db_query(
            conn,
            "SELECT community_id FROM maludb_community WHERE community_id = %s",
            [community_id],
        )
        if not exists:
            json_error("not_found", f"Community {community_id} not found.", 404)
        rows = db_query(
            conn,
            """SELECT m.object_kind, m.object_id, m.score, s.canonical_name, s.aliases
                 FROM maludb_community_membership m
                 LEFT JOIN maludb_subject s
                   ON m.object_kind = 'subject' AND s.subject_id = m.object_id
                WHERE m.community_id = %s
                ORDER BY m.object_id
                LIMIT %s""",
            [community_id, limit],
        )
        for r in rows:
            r["object_id"] = int(r["object_id"])
            r["score"] = float(r["score"]) if r["score"] is not None else None
            aliases = r.pop("aliases", None) or []
            r["label"] = aliases[0] if aliases else r["canonical_name"]
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"community_id": community_id, "members": rows}


# ===========================================================================
# POST /v1/graph/import — bulk import of a Graphify node-link graph
# ===========================================================================


def _clean_text(value, max_len: int) -> str:
    """Strip control characters and cap length."""
    return _CONTROL_CHARS_RE.sub("", str(value)).strip()[:max_len]


def _link_confidence(raw) -> float | None:
    """Map Graphify's EXTRACTED/INFERRED/AMBIGUOUS (or a numeric) to [0,1]."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return _CONFIDENCE_MAP.get(str(raw).strip().upper())


@router.post("/v1/graph/import")
async def graph_import(auth: Auth, request: Request):
    """
    Import a Graphify graph (NetworkX node-link JSON) into the tenant graph.

    Body: {
      "namespace": "my-repo",                  # required; prefixes canonical names
      "provenance": "graphify-0.9.6",          # optional free text on the namespace subject
      "graph": {"nodes": [...], "links": [...]}  # "edges" accepted as alias of "links"
      "options": {"chunk_size": 500}           # optional
    }

    Nodes become subjects (canonical_name = "<namespace>/<node id>", label as
    alias + attribute); links become SVO statements (relation as verb, with
    numeric confidence). Idempotent: subjects upsert by canonical name and
    statements by (subject, verb, object) identity, so re-importing the same
    graph updates rather than duplicates. Runs in a single transaction.

    Note: the core ingest counts statement upserts as "created", so
    edges.created on a re-import reports the upserted total even though no
    new rows were inserted; nodes.created/resolved distinguish correctly.
    """
    body = await request.json()
    if not isinstance(body, dict):
        json_error("validation_failed", "Body must be a JSON object.", 422)

    namespace = str(body.get("namespace") or "").strip()
    if not namespace:
        json_error("missing_field", 'Field "namespace" is required.', 400)
    if not _NAMESPACE_RE.match(namespace):
        json_error(
            "validation_failed",
            '"namespace" must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$.',
            422,
        )

    graph = body.get("graph")
    if not isinstance(graph, dict):
        json_error("missing_field", 'Field "graph" (node-link object) is required.', 400)

    nodes = graph.get("nodes")
    links = graph.get("links", graph.get("edges", []))
    if not isinstance(nodes, list) or not nodes:
        json_error("validation_failed", '"graph.nodes" must be a non-empty array.', 422)
    if not isinstance(links, list):
        json_error("validation_failed", '"graph.links" must be an array.', 422)
    if len(nodes) > _MAX_NODES:
        json_error("validation_failed", f'"graph.nodes" exceeds the {_MAX_NODES} node cap.', 422)
    if len(links) > _MAX_LINKS:
        json_error("validation_failed", f'"graph.links" exceeds the {_MAX_LINKS} link cap.', 422)

    options = body.get("options") or {}
    chunk_size = options.get("chunk_size", 500)
    if not isinstance(chunk_size, int) or not (50 <= chunk_size <= 5000):
        json_error("validation_failed", '"options.chunk_size" must be an integer in [50, 5000].', 422)

    provenance = _clean_text(body.get("provenance") or "graphify", 200)

    # ---- preferred path: one in-core call (core >= 0.103.0) ---------------
    # maludb_graph_import owns the whole transformation (types, subjects,
    # SVO edges, communities); this endpoint just validates HTTP input and
    # relays the report. The client-side path below remains as a fallback
    # for older cores.
    def _core_import(conn):
        has_fn = db_query(
            conn,
            "SELECT to_regproc('maludb_graph_import') IS NOT NULL AS ok",
        )[0]["ok"]
        if not has_fn:
            return None
        core_options = {"provenance": provenance}
        if options.get("resolve_external") is True:
            core_options["resolve_external"] = True
        if isinstance(options.get("algorithm"), str):
            core_options["algorithm"] = options["algorithm"]
        return db_query(
            conn,
            "SELECT maludb_graph_import(%s, %s::jsonb, %s::jsonb) AS report",
            [namespace, json.dumps({"nodes": nodes, "links": links}),
             json.dumps(core_options)],
        )[0]["report"]

    core_report = db_tx_core(auth.conn, _core_import)
    if core_report is not None:
        n = core_report.get("nodes") or {}
        e = core_report.get("edges") or {}
        comm = core_report.get("communities")
        return {
            "namespace": namespace,
            "nodes": {
                "received": int(n.get("received") or 0),
                "imported": int(n.get("received") or 0),
                "created": int(n.get("created") or 0),
                "resolved": int(n.get("resolved") or 0),
            },
            "edges": {
                "received": int(e.get("received") or 0),
                "imported": int(e.get("received") or 0),
                "created": int(e.get("created") or 0),
            },
            "verbs_created": int(core_report.get("verbs_created") or 0),
            "communities": (
                {"stored": int(comm.get("communities") or 0),
                 "members": int(comm.get("members") or 0)}
                if comm else None
            ),
            "chunks": 1,
            "skipped": (core_report.get("skipped") or [])[:_MAX_SKIPPED_REPORTED],
        }

    # ---- normalize nodes (fallback for core < 0.103.0) --------------------
    skipped: list[dict] = []
    subjects_by_id: dict[str, dict] = {}
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            skipped.append({"section": "nodes", "index": i, "reason": "not an object"})
            continue
        node_id = _clean_text(n.get("id") or "", 512)
        if not node_id:
            skipped.append({"section": "nodes", "index": i, "reason": "missing id"})
            continue
        if node_id in subjects_by_id:
            skipped.append({"section": "nodes", "index": i, "reason": f"duplicate id {node_id!r}"})
            continue

        label = _clean_text(n.get("label") or "", 256)
        node_type = _clean_text(n.get("file_type") or n.get("type") or "concept", 60) or "concept"
        attributes = []
        for attr in ("label", "source_file", "source_location", "community", "file_type"):
            if n.get(attr) is not None and str(n.get(attr)).strip() != "":
                attributes.append(
                    {"attr_name": f"graphify_{attr}", "value_text": _clean_text(n[attr], 2000)}
                )
        subject = {
            "key": node_id,
            "name": f"{namespace}/{node_id}",
            "type": node_type,
        }
        if label and label != node_id:
            subject["aliases"] = [label]
        if attributes:
            subject["attributes"] = attributes
        subjects_by_id[node_id] = subject

    # ---- normalize links -------------------------------------------------
    edges: list[dict] = []
    for i, link in enumerate(links):
        if not isinstance(link, dict):
            skipped.append({"section": "links", "index": i, "reason": "not an object"})
            continue
        src = _clean_text(link.get("source") or "", 512)
        tgt = _clean_text(link.get("target") or "", 512)
        if src not in subjects_by_id or tgt not in subjects_by_id:
            skipped.append({"section": "links", "index": i, "reason": "unknown source/target node id"})
            continue
        relation = _clean_text(link.get("relation") or "related_to", 120) or "related_to"
        edge = {"subject": src, "verb": relation, "object": tgt}
        confidence = _link_confidence(link.get("confidence"))
        if confidence is not None:
            edge["confidence"] = confidence
        edges.append(edge)

    subject_list = list(subjects_by_id.values())

    # ---- namespace root subject (namespaces become discoverable) ----------
    root_subject = {
        "key": "$namespace",
        "name": namespace,
        "type": "graph_namespace",
        "attributes": [{"attr_name": "provenance", "value_text": provenance}],
    }

    # ---- chunked ingest in one transaction --------------------------------
    def _import(conn):
        # Unseen node types are registered into the global subject-type
        # catalog when the core is >= 0.102.0 (maludb_register_subject_type
        # facade); on older cores they fall back to a seeded generic with the
        # declared type preserved in the graphify_type attribute. Types that
        # can't be expressed as a valid catalog name always fall back.
        catalog = {
            r["subject_type"]
            for r in db_query(conn, "SELECT subject_type FROM maludb_subject_type")
        }
        can_register = db_query(
            conn,
            "SELECT to_regproc('maludb_register_subject_type') IS NOT NULL AS ok",
        )[0]["ok"]
        fallback = next((t for t in ("concept", "other") if t in catalog), None)
        if fallback is None:
            json_error(
                "validation_failed",
                "Tenant subject-type catalog has no generic type "
                "('concept' or 'other') to map graph nodes onto.",
                422,
            )
        registrable = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
        for subject in [root_subject, *subject_list]:
            declared = subject["type"]
            if declared in catalog:
                continue
            slug = re.sub(r"[^a-z0-9_]", "_", declared.lower())
            if can_register and registrable.match(slug):
                db_query(
                    conn,
                    "SELECT maludb_register_subject_type(%s) AS registered",
                    [slug],
                )
                catalog.add(slug)
                if slug != declared:
                    subject.setdefault("attributes", []).append(
                        {"attr_name": "graphify_type", "value_text": declared}
                    )
                subject["type"] = slug
            else:
                subject.setdefault("attributes", []).append(
                    {"attr_name": "graphify_type", "value_text": declared}
                )
                subject["type"] = fallback

        totals = {
            "subjects_created": 0,
            "subjects_resolved": 0,
            "verbs_created": 0,
            "edges_created": 0,
            "chunks": 0,
        }

        def _ingest(payload: dict, count_subjects: bool = False):
            rows = db_query(
                conn,
                "SELECT maludb_memory_ingest_extraction(%s::jsonb) AS report",
                [json.dumps(payload)],
            )
            report = rows[0]["report"]
            created = report.get("created", {})
            resolved = report.get("resolved", {})
            # Pass 2 re-lists edge endpoints to satisfy the ingest contract's
            # same-payload key resolution; only pass 1 counts subjects, so
            # those re-resolves don't inflate the report.
            if count_subjects:
                totals["subjects_created"] += int(created.get("subjects", 0))
                totals["subjects_resolved"] += int(resolved.get("subjects", 0))
            totals["verbs_created"] += int(created.get("verbs", 0))
            totals["edges_created"] += int(created.get("edges", 0))
            totals["chunks"] += 1
            for item in report.get("skipped", []):
                if len(skipped) < _MAX_SKIPPED_REPORTED:
                    skipped.append(item)

        # Pass 1: subjects (root first so the namespace exists even for
        # a nodes-only import).
        _ingest({"subjects": [root_subject]}, count_subjects=True)
        for i in range(0, len(subject_list), chunk_size):
            _ingest({"subjects": subject_list[i : i + chunk_size]}, count_subjects=True)

        # Pass 2: edges. Each chunk re-lists its endpoint subjects (name-only
        # entries resolve idempotently to the existing rows) so chunks are
        # self-contained — the ingest contract resolves from/to against keys
        # in the same payload.
        for i in range(0, len(edges), chunk_size):
            chunk = edges[i : i + chunk_size]
            endpoint_ids = {e["subject"] for e in chunk} | {e["object"] for e in chunk}
            resolve_subjects = [
                {
                    "key": nid,
                    "name": subjects_by_id[nid]["name"],
                    "type": subjects_by_id[nid]["type"],
                }
                for nid in sorted(endpoint_ids)
            ]
            _ingest({"subjects": resolve_subjects, "edges": chunk})

        # Pass 3: communities. Graphify tags nodes with a community id at
        # cluster time; store them first-class when the core has the
        # 0.102.0 community facade (replace semantics per namespace).
        by_community: dict[int, list[str]] = {}
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                continue
            node_id = _clean_text(n.get("id") or "", 512)
            if node_id not in subjects_by_id or n.get("community") is None:
                continue
            try:
                key = int(n["community"])
            except (TypeError, ValueError):
                continue
            by_community.setdefault(key, []).append(subjects_by_id[node_id]["name"])
        if by_community:
            has_facade = db_query(
                conn,
                "SELECT to_regproc('maludb_community_replace') IS NOT NULL AS ok",
            )[0]["ok"]
            if has_facade:
                payload = [
                    {"key": key, "members": members}
                    for key, members in sorted(by_community.items())
                ]
                report = db_query(
                    conn,
                    "SELECT maludb_community_replace(%s, %s, %s::jsonb) AS report",
                    [namespace, "louvain", json.dumps(payload)],
                )[0]["report"]
                totals["communities"] = {
                    "stored": int(report.get("communities", 0)),
                    "members": int(report.get("members", 0)),
                }
            else:
                totals["communities"] = {
                    "stored": 0,
                    "members": 0,
                    "note": "core lacks maludb_community_replace (needs >= 0.102.0)",
                }

        return totals

    totals = db_tx_core(auth.conn, _import)

    return {
        "namespace": namespace,
        "nodes": {
            "received": len(nodes),
            "imported": len(subject_list),
            "created": totals["subjects_created"],
            "resolved": totals["subjects_resolved"],
        },
        "edges": {
            "received": len(links),
            "imported": len(edges),
            "created": totals["edges_created"],
        },
        "verbs_created": totals["verbs_created"],
        "communities": totals.get("communities"),
        "chunks": totals["chunks"],
        "skipped": skipped[:_MAX_SKIPPED_REPORTED],
    }


# ===========================================================================
# Data-model graph (core >= 0.104.0): refresh + describe
# ===========================================================================


@router.post("/v1/datamodel/refresh")
async def datamodel_refresh(auth: Auth, request: Request):
    """
    Introspect the tenant's database objects (tables, views, routines,
    triggers, FKs, view dependencies) into the data-model graph namespace
    via maludb_datamodel_refresh. Body (optional):
    {"namespace": "datamodel", "schemas": ["maludb_core"]}.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    namespace = str(body.get("namespace") or "datamodel").strip()
    schemas = body.get("schemas")
    if schemas is not None and (
        not isinstance(schemas, list) or not all(isinstance(s, str) for s in schemas)
    ):
        json_error("validation_failed", '"schemas" must be an array of schema names.', 422)

    def _refresh(conn):
        has_fn = db_query(
            conn,
            "SELECT to_regproc('maludb_datamodel_refresh') IS NOT NULL AS ok",
        )[0]["ok"]
        if not has_fn:
            json_error(
                "not_supported",
                "maludb_datamodel_refresh is not available (requires maludb_core >= 0.104.0).",
                409,
            )
        return db_query(
            conn,
            "SELECT maludb_datamodel_refresh(%s, %s::name[]) AS report",
            [namespace, schemas],
        )[0]["report"]

    report = db_tx_core(auth.conn, _refresh)
    return {"report": report}


@router.get("/v1/datamodel/describe")
def datamodel_describe(
    auth: Auth,
    relation: str = Query(min_length=1, max_length=200),
):
    """Live catalog description (columns, pk, FKs in/out) of one relation."""

    def _describe(conn):
        has_fn = db_query(
            conn,
            "SELECT to_regproc('maludb_datamodel_describe') IS NOT NULL AS ok",
        )[0]["ok"]
        if not has_fn:
            json_error(
                "not_supported",
                "maludb_datamodel_describe is not available (requires maludb_core >= 0.104.0).",
                409,
            )
        return db_query(
            conn,
            "SELECT maludb_datamodel_describe(%s) AS report",
            [relation],
        )[0]["report"]

    return {"relation": relation, "describe": db_tx_core(auth.conn, _describe)}
