-- 078_api_token_scope.sql
-- The platform gains a browser-facing JSON API, and it needs its own kind of token.
--
-- Decided 2026-09-18, for the APEX-UI front end. Until now `mcp_access_tokens` served one
-- surface, so a token was a token. With a REST API alongside the MCP servers that stops being
-- true: the two have different blast radii — an MCP token reaches the whole records tool surface,
-- an API token reaches only the endpoints under /api/v1 — and revoking access to one should not
-- have to mean revoking the other.
--
-- So a token carries a scope, and each surface accepts only its own. A wrong-scope token is
-- rejected exactly as a missing one is, with the same body, because "valid token, wrong surface"
-- is still information an attacker can use.
--
-- Existing rows are backfilled to 'mcp', which is what every one of them is.

BEGIN;

ALTER TABLE mcp_access_tokens
    ADD COLUMN scope text NOT NULL DEFAULT 'mcp'
        CHECK (scope IN ('mcp', 'api'));

COMMENT ON COLUMN mcp_access_tokens.scope IS
    'Which surface this token authenticates: mcp = the records/activity MCP servers, '
    'api = the JSON API under /api/v1. A token is never valid on the other surface.';

CREATE INDEX mcp_access_tokens_scope_idx ON mcp_access_tokens (scope) WHERE revoked_at IS NULL;

-- An API read is not a screen view. Logging it as 'web' would corrupt the activity memory that
-- answers "who looked at what, and from where" — the one thing that cannot be backfilled.
ALTER TABLE activity_log DROP CONSTRAINT activity_log_source_check;
ALTER TABLE activity_log ADD CONSTRAINT activity_log_source_check CHECK (
    source IN ('web', 'assistant', 'mcp', 'cron', 'agent', 'desk', 'webhook', 'portal', 'api')
);

COMMIT;
