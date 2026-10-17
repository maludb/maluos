"""
FastAPI application — entry point.

Creates the app, registers exception handlers, adds per-request middleware
(SqlTracer setup, connection cleanup, debug injection), and mounts the
health endpoint.
"""

from __future__ import annotations

import json

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app import config
from app.database import TenantDatabaseError
from app.errors import (
    APIError,
    api_error_handler,
    database_error_handler,
    secret_format_error_handler,
    store_key_error_handler,
    tenant_db_error_handler,
    unhandled_error_handler,
)
from app.routers import (
    agent_memory,
    attributes,
    chat,
    documents,
    episodes,
    graph,
    llm_config,
    mcp,
    memory,
    memory_answer,
    memory_maintenance,
    memory_notes,
    model_prompts,
    notes,
    objects,
    pools,
    principals,
    projects,
    rest,
    scoping,
    skills,
    skills_fleet,
    statements,
    subjects,
    tokens,
    types,
    verbs,
)
from app.sql_log import SqlTracer, set_tracer
from app.store_crypto import SecretFormatError, StoreKeyError

# ---------------------------------------------------------------------------
# Create the FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="MaluDB API")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(agent_memory.router)
app.include_router(scoping.router)  # before skills/pools: /v1/skills/{id}/review etc. are its own
app.include_router(attributes.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(episodes.router)
app.include_router(graph.router)
app.include_router(llm_config.router)
app.include_router(mcp.router)
app.include_router(memory.router)
app.include_router(memory_answer.router)
app.include_router(memory_maintenance.router)
app.include_router(memory_notes.router)
app.include_router(model_prompts.router)
app.include_router(notes.router)
app.include_router(objects.router)
app.include_router(pools.router)
app.include_router(principals.router)
app.include_router(projects.router)
app.include_router(rest.router_rest)
app.include_router(rest.router_tables)
app.include_router(skills_fleet.router)  # before skills: /v1/skills/resolve must not match /v1/skills/{id}
app.include_router(skills.router)
app.include_router(statements.router)
app.include_router(subjects.router)
app.include_router(tokens.router)
app.include_router(verbs.router)
app.include_router(types.router)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(psycopg.errors.DatabaseError, database_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(TenantDatabaseError, tenant_db_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(StoreKeyError, store_key_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(SecretFormatError, secret_format_error_handler)  # type: ignore[arg-type]
# Last-resort catch-all so unexpected Python exceptions still return the
# standard JSON error shape instead of Starlette's bare HTML 500.
app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Per-request middleware — SqlTracer + connection cleanup + debug injection
# ---------------------------------------------------------------------------


class TracerMiddleware(BaseHTTPMiddleware):
    """Middleware that creates a fresh SqlTracer per request, sets endpoint
    metadata, and optionally injects debug SQL trace into JSON responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Create and install a fresh tracer for this request
        tracer = SqlTracer()
        tracer.method = request.method
        tracer.uri = str(request.url.path)
        if request.url.query:
            tracer.uri += f"?{request.url.query}"
        # Derive an endpoint name from the path (similar to PHP's basename of SCRIPT_FILENAME)
        tracer.endpoint = request.url.path.rstrip("/").rsplit("/", 1)[-1] or "root"
        set_tracer(tracer)

        response = await call_next(request)

        # Debug injection: if DEBUG_ENABLED and ?debug=1, inject meta.debug into JSON
        # responses — but only on mounts that own the {"…", "meta": …} envelope.
        # /rest/v1 is wire-compatible with PostgREST (bare arrays / bare row objects)
        # and /mcp returns bare JSON-RPC bodies: a phantom "meta" member there would
        # be read by the client as payload data (leaking the SQL trace into it).
        if (
            config.DEBUG_ENABLED
            and request.query_params.get("debug") == "1"
            and not request.url.path.startswith(("/rest/", "/mcp"))
            and response.headers.get("content-type", "").startswith("application/json")
        ):
            # Read the response body
            body_chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    body_chunks.append(chunk)
                else:
                    body_chunks.append(chunk.encode("utf-8"))
            body_bytes = b"".join(body_chunks)

            try:
                data = json.loads(body_bytes)
                if isinstance(data, dict):
                    if "meta" not in data:
                        data["meta"] = {}
                    data["meta"]["debug"] = {
                        "endpoint": tracer.endpoint,
                        "queries": tracer.queries,
                    }
                    # Carry over the original headers (e.g. Content-Range) —
                    # content-length/type are recomputed for the new body.
                    headers = {
                        k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")
                    }
                    return JSONResponse(
                        content=data,
                        status_code=response.status_code,
                        headers=headers,
                    )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # If we couldn't parse/modify, return original body
            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response


app.add_middleware(TracerMiddleware)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """Health check — always returns 200."""
    return {"status": "ok"}
