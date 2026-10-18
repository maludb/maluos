-- MaluOS vault and ledger: tenant-schema objects. Applied as the tenant role by
-- the first-boot component (idempotent; re-run on every provisioning).
-- Secret VALUES are never here: they are blobs under /var/lib/maluos-vault.

CREATE TABLE IF NOT EXISTS maluos_compartment (
    compartment_id      bigserial PRIMARY KEY,
    name                text NOT NULL UNIQUE CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,119}$'),
    owner_principal_ref text,                        -- personal compartment; NULL = shared
    scope               text,                        -- informational for shared compartments
    lock_mode           text NOT NULL DEFAULT 'always_unlocked'
                        CHECK (lock_mode IN ('always_unlocked','manual','login')),
    locked              boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maluos_secret (
    secret_id           bigserial PRIMARY KEY,
    compartment_id      bigint NOT NULL REFERENCES maluos_compartment(compartment_id) ON DELETE CASCADE,
    name                text NOT NULL CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9_.@-]{0,119}$'),
    kind                text NOT NULL DEFAULT 'api_key' CHECK (kind IN ('api_key','token','password','generic')),
    provider            text,                        -- anthropic, openai, ollama_cloud, ...
    env_var             text,                        -- variable name for `maluctl secret exec`
    cred_ref            text NOT NULL,               -- blob id in the vault store, never a value
    previous_cred_ref   text,
    grace_until         timestamptz,
    created_by          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    rotated_at          timestamptz,
    expires_at          timestamptz,
    UNIQUE (compartment_id, name)
);

CREATE TABLE IF NOT EXISTS maluos_secret_grant (
    grant_id            bigserial PRIMARY KEY,
    secret_id           bigint NOT NULL REFERENCES maluos_secret(secret_id) ON DELETE CASCADE,
    grantee_kind        text NOT NULL CHECK (grantee_kind IN ('principal','scope')),
    grantee_ref         text NOT NULL,
    level               text NOT NULL CHECK (level IN ('use','read')),
    budget              jsonb,
    expires_at          timestamptz,
    granted_by          text,
    granted_at          timestamptz NOT NULL DEFAULT now(),
    revoked_at          timestamptz,
    revoked_by          text
);
CREATE UNIQUE INDEX IF NOT EXISTS maluos_secret_grant_live_uq
    ON maluos_secret_grant (secret_id, grantee_kind, grantee_ref) WHERE revoked_at IS NULL;

-- Slice 4 uses this; the shape is fixed now so the ledger can reference it.
CREATE TABLE IF NOT EXISTS maluos_delegation (
    delegation_id       bigserial PRIMARY KEY,
    from_principal_ref  text NOT NULL,
    to_principal_ref    text NOT NULL,
    secret_id           bigint REFERENCES maluos_secret(secret_id) ON DELETE CASCADE,  -- NULL = all of from's secrets
    budget              jsonb,
    expires_at          timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    revoked_at          timestamptz
);

-- The ledger: one row per secret event now, per model call from slice 2.
CREATE TABLE IF NOT EXISTS maluos_ledger (
    ledger_id           bigserial PRIMARY KEY,
    ts                  timestamptz NOT NULL DEFAULT now(),
    event               text NOT NULL,      -- secret.add/read/use/rotate/delete, grant.add/revoke, compartment.*, model.call
    principal_ref       text,               -- effective principal
    linux_user          text,
    linux_uid           integer,
    process_ref         text,               -- comm@unit when known
    broker_ref          text,               -- the broker that asserted principal_ref (the gateway)
    compartment         text,
    secret_name         text,
    secret_id           bigint,
    grant_level         text,
    purpose             text,
    status              text NOT NULL CHECK (status IN ('ok','denied','error','noop')),
    reason              text,
    -- model calls (slice 2+)
    class               text,
    tier                text,
    requested_model     text,
    route               jsonb,
    attempts            integer,
    backend             text,
    model               text,
    queue_wait_ms       integer,
    service_ms          integer,
    gpu_ms              integer,
    tokens_in           integer,
    tokens_out          integer,
    tokens_cached       integer,
    cost_est            numeric(14,6),
    cost_actual         numeric(14,6),
    currency            text,
    error_class         text,
    provider_request_id text,
    task_ref            text,
    episode_id          bigint,
    detail              jsonb
);
CREATE INDEX IF NOT EXISTS maluos_ledger_ts_idx ON maluos_ledger (ts);
CREATE INDEX IF NOT EXISTS maluos_ledger_principal_idx ON maluos_ledger (principal_ref, ts);
CREATE INDEX IF NOT EXISTS maluos_ledger_secret_idx ON maluos_ledger (secret_id, ts);

-- Append-only, for everyone including the owner (retention jobs disable the trigger explicitly).
CREATE OR REPLACE FUNCTION maluos_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'maluos_ledger is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;
DROP TRIGGER IF EXISTS maluos_ledger_append_only ON maluos_ledger;
CREATE TRIGGER maluos_ledger_append_only BEFORE UPDATE OR DELETE ON maluos_ledger
    FOR EACH ROW EXECUTE FUNCTION maluos_ledger_append_only();

-- What a principal-bound session may see of the ledger: its own rows.
CREATE OR REPLACE VIEW maluos_ledger_mine WITH (security_invoker = true) AS
    SELECT * FROM maluos_ledger
     WHERE principal_ref = current_setting('maludb_core.principal_ref', true)
        OR broker_ref    = current_setting('maludb_core.principal_ref', true);

-- Daily roll-up for reports (FR-41, FR-43).
CREATE OR REPLACE VIEW maluos_ledger_daily AS
    SELECT date_trunc('day', ts)::date AS day, principal_ref, linux_user, event, status, compartment, secret_name,
           backend, model, count(*) AS events, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
           sum(cost_actual) AS cost_actual
      FROM maluos_ledger
     GROUP BY 1,2,3,4,5,6,7,8,9;
