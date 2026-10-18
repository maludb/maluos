-- MaluOS inference gateway: tenant-schema objects. Applied as the tenant role by
-- the first-boot component (idempotent). The ledger itself comes from
-- maluos-vault's schema (maluos_ledger), which the gateway writes model.call rows to.

CREATE TABLE IF NOT EXISTS maluos_backend (
    backend_id   bigserial PRIMARY KEY,
    name         text NOT NULL UNIQUE CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
    kind         text NOT NULL CHECK (kind IN ('ollama_local','ollama_cloud','anthropic','openai','openai_compat','mock')),
    endpoint     text NOT NULL,
    secret_ref   text,                       -- vault reference (compartment/name), cloud backends
    capacity     jsonb NOT NULL DEFAULT '{}'::jsonb,   -- max_concurrent, ...
    options      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- keep_alive, keep_warm, ...
    enabled      boolean NOT NULL DEFAULT true,
    health       jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maluos_tier (
    name         text PRIMARY KEY CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
    description  text,
    requirements jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Caller-visible names: a tier has several aliases in ladder order (position);
-- a plain alias is one name bound to one backend model.
CREATE TABLE IF NOT EXISTS maluos_alias (
    name         text NOT NULL CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9:/_.@-]{0,127}$'),
    tier         text REFERENCES maluos_tier(name) ON DELETE CASCADE,
    backend      text NOT NULL REFERENCES maluos_backend(name) ON DELETE CASCADE,
    model        text NOT NULL,
    position     integer NOT NULL DEFAULT 0,
    enabled      boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (name, backend, model)
);

CREATE TABLE IF NOT EXISTS maluos_class (
    name            text PRIMARY KEY,
    priority        integer NOT NULL,          -- lower runs first; strict between classes
    weight          integer NOT NULL DEFAULT 1,
    max_queue       integer NOT NULL DEFAULT 100,
    max_wait_s      integer,                   -- reject when expected wait is above (NULL: never)
    fallback_wait_s integer,                   -- route to the cloud when expected local wait is above (slice 3)
    description     text
);

CREATE TABLE IF NOT EXISTS maluos_policy (
    policy_id              bigserial PRIMARY KEY,
    subject_kind           text NOT NULL CHECK (subject_kind IN ('default','principal','scope')),
    subject_ref            text NOT NULL DEFAULT '',
    allowed_tiers          text[],              -- NULL: all
    allowed_backends       text[],              -- NULL: all
    cloud_allowed          boolean NOT NULL DEFAULT true,
    default_class          text REFERENCES maluos_class(name),
    max_egress_sensitivity text,
    ladder                 jsonb,
    budget                 jsonb,
    updated_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_kind, subject_ref)
);

CREATE TABLE IF NOT EXISTS maluos_token (
    token_id      bigserial PRIMARY KEY,
    principal_ref text NOT NULL,
    name          text,
    token_hash    text NOT NULL UNIQUE,        -- sha256 hex of the bearer token
    created_by    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    revoked_at    timestamptz,
    last_used_at  timestamptz
);

-- Live state the gateway publishes every few seconds (for the MCP tool and reports).
CREATE TABLE IF NOT EXISTS maluos_gateway_status (
    id          integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    status      jsonb NOT NULL
);

-- MCP tool: model_status (queue depth, expected wait per class and tier, backends).
CREATE OR REPLACE FUNCTION maluos_model_status(args jsonb, context jsonb) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    v_status jsonb;
    v_at     timestamptz;
BEGIN
    SELECT status, updated_at INTO v_status, v_at FROM maluos_gateway_status WHERE id = 1;
    IF v_status IS NULL THEN
        CALL mc2db.put_object(jsonb_build_object(
            'content', jsonb_build_array(jsonb_build_object('type','text','text','gateway status unknown (maluos-gateway not running?)')),
            'structuredContent', jsonb_build_object('available', false), 'isError', false));
        RETURN;
    END IF;
    CALL mc2db.put_object(jsonb_build_object(
        'content', jsonb_build_array(jsonb_build_object('type','text','text',
            format('gateway: %s queued, %s running; expected wait interactive %ss, agent %ss, batch %ss; updated %s',
                   v_status->'queue'->>'queued', v_status->'queue'->>'running',
                   v_status->'expected_wait_s'->>'interactive', v_status->'expected_wait_s'->>'agent',
                   v_status->'expected_wait_s'->>'batch', v_at))),
        'structuredContent', v_status || jsonb_build_object('available', true, 'updated_at', v_at,
                                                             'stale', (now() - v_at) > interval '30 seconds'),
        'isError', false));
END $$;
-- The listener calls tools with its own pinned search_path: bind this function to the tenant schema.
ALTER FUNCTION maluos_model_status(jsonb, jsonb) SET search_path FROM CURRENT;
