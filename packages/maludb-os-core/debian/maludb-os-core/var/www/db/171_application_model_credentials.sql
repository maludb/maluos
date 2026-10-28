-- 171: K24 — an application's credential at the ledger proxy (design: /srv/apps/knowledge/docs/knowledge-design.md §12, owner's D4/D15, 2026-10-05).
-- An application that makes model calls of its own through a memory engine (Knowledge: MaluDB's extraction, embedding and answers) points the
-- engine's provider URL at the ledger proxy with this credential, so the call is priced, ledgered and stamped with the application and lands on the
-- AI statement. It is NOT the application token (that opens the kernel's directory, ledger-export and chat endpoints and must not travel into a
-- third service). One live credential per application; shown once, only its sha256 kept; revocable; confined to named models (a call to any other
-- model is refused — the ledger row must be able to name what it spent on) and to an optional monthly cap. Additive.
BEGIN;

CREATE TABLE application_model_credentials (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id        bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    label                 text   NOT NULL,
    token_hash            text   NOT NULL UNIQUE,
    allowed_model_ids     bigint[] NOT NULL CHECK (cardinality(allowed_model_ids) > 0),
    monthly_budget_amount numeric(14,2) CHECK (monthly_budget_amount IS NULL OR monthly_budget_amount >= 0),
    acting_member_id      bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,   -- who minted it; the ledger's acting member
    created_at            timestamptz NOT NULL DEFAULT now(),
    last_used_at          timestamptz,
    revoked_at            timestamptz
);
CREATE UNIQUE INDEX application_model_credentials_one_live ON application_model_credentials (application_id) WHERE revoked_at IS NULL;

-- The proxy (role app_runner) holds no grant on the table: it resolves a presented key through this function only.
CREATE FUNCTION app_model_credential_resolve(p_hash text)
RETURNS TABLE (credential_id bigint, application_id bigint, application_name text, acting_member_id bigint,
               allowed_model_ids bigint[], monthly_budget_amount numeric)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    UPDATE application_model_credentials c SET last_used_at = now()
     WHERE c.token_hash = p_hash AND c.revoked_at IS NULL
       AND (c.last_used_at IS NULL OR c.last_used_at < now() - interval '1 minute');
    RETURN QUERY
    SELECT c.id, c.application_id, a.name, c.acting_member_id, c.allowed_model_ids, c.monthly_budget_amount
      FROM application_model_credentials c
      JOIN applications a ON a.id = c.application_id
     WHERE c.token_hash = p_hash AND c.revoked_at IS NULL AND a.status IN ('active', 'degraded');
END $$;

-- This month's spend by one application's own calls (no agent behind them), money plus notional, as agents' budgets count.
CREATE FUNCTION application_model_month_cost(p_application_id bigint)
RETURNS numeric LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT COALESCE(sum(cost + notional_cost), 0) FROM prompt_ledger
     WHERE application_id = p_application_id AND agent_run_id IS NULL AND agent_member_id IS NULL
       AND occurred_at >= date_trunc('month', now())
$$;

REVOKE ALL ON application_model_credentials FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON application_model_credentials TO app_rw;
REVOKE ALL ON FUNCTION app_model_credential_resolve(text), application_model_month_cost(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_model_credential_resolve(text), application_model_month_cost(bigint) TO app_runner;
GRANT INSERT ON prompt_ledger TO app_runner;      -- already held; restated so this migration stands alone

COMMIT;
