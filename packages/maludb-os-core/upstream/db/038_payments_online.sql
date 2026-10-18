-- 038_payments_online.sql
-- Online payment collection (decided in v1, 2026-09-17). The provider sits behind an
-- adapter: nothing here is provider-specific except the `provider` value and the raw
-- webhook payloads. Credentials live in tenant_secrets and never reach MCP.
-- Questions: S15–S22, S4, S11. approval_request_id FK on refunds is added in 044.

BEGIN;

CREATE TABLE payment_providers (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider            text NOT NULL,                                -- 'stripe' (first adapter, open point)
    display_name        text NOT NULL,
    mode                text NOT NULL DEFAULT 'test' CHECK (mode IN ('test', 'live')),
    account_ref         text,                                         -- provider account id
    api_secret_id       bigint REFERENCES tenant_secrets(id) ON DELETE RESTRICT,
    webhook_secret_id   bigint REFERENCES tenant_secrets(id) ON DELETE RESTRICT,
    status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'error')),
    is_default          boolean NOT NULL DEFAULT false,
    connected_at        timestamptz,
    last_event_at       timestamptz,
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX payment_providers_one_default_idx ON payment_providers ((true))
    WHERE is_default AND status = 'active';

-- A payment link / checkout session for one invoice (S16, S21).
CREATE TABLE payment_links (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id        bigint NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    provider_id       bigint NOT NULL REFERENCES payment_providers(id) ON DELETE RESTRICT,
    provider_ref      text NOT NULL,
    url               text NOT NULL,
    amount            numeric(14,2) NOT NULL CHECK (amount > 0),
    currency          char(3) NOT NULL,
    status            text NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'completed', 'expired', 'cancelled')),
    expires_at        timestamptz,
    first_opened_at   timestamptz,
    completed_at      timestamptz,
    created_by        bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, provider_ref)
);
CREATE INDEX payment_links_invoice_idx ON payment_links (invoice_id);
CREATE INDEX payment_links_open_idx    ON payment_links (created_at) WHERE status = 'open';

-- Payouts from the provider to the bank (S18).
CREATE TABLE payouts (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id    bigint NOT NULL REFERENCES payment_providers(id) ON DELETE RESTRICT,
    provider_ref   text NOT NULL,
    amount         numeric(14,2) NOT NULL,
    fee_total      numeric(14,2) NOT NULL DEFAULT 0,
    currency       char(3) NOT NULL,
    status         text NOT NULL CHECK (status IN ('pending', 'in_transit', 'paid', 'failed', 'cancelled')),
    arrival_date   date,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, provider_ref)
);
CREATE INDEX payouts_arrival_idx ON payouts (arrival_date);

-- A charge at the provider (succeeded or failed). Succeeded ones also produce a row in
-- payments (source 'online') allocated to the invoice; unmatched ones are S19.
CREATE TABLE provider_payments (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id      bigint NOT NULL REFERENCES payment_providers(id) ON DELETE RESTRICT,
    provider_ref     text NOT NULL,
    payment_link_id  bigint REFERENCES payment_links(id) ON DELETE SET NULL,
    invoice_id       bigint REFERENCES invoices(id) ON DELETE SET NULL,
    amount           numeric(14,2) NOT NULL CHECK (amount > 0),
    fee_amount       numeric(14,2) NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
    net_amount       numeric(14,2) GENERATED ALWAYS AS (amount - fee_amount) STORED,
    currency         char(3) NOT NULL,
    status           text NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded',
                                                     'partially_refunded', 'disputed')),
    failure_code     text,                                            -- S15
    failure_message  text,
    paid_at          timestamptz,
    payout_id        bigint REFERENCES payouts(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, provider_ref)
);
CREATE INDEX provider_payments_invoice_idx ON provider_payments (invoice_id);
CREATE INDEX provider_payments_failed_idx  ON provider_payments (created_at) WHERE status = 'failed';
CREATE INDEX provider_payments_payout_idx  ON provider_payments (payout_id);

ALTER TABLE payments
    ADD CONSTRAINT payments_provider_payment_fk
    FOREIGN KEY (provider_payment_id) REFERENCES provider_payments(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX payments_provider_payment_idx ON payments (provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;

-- Webhook inbox: every provider event stored once (idempotency), processed after.
CREATE TABLE provider_events (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id          bigint NOT NULL REFERENCES payment_providers(id) ON DELETE RESTRICT,
    provider_event_id    text NOT NULL,
    event_type           text NOT NULL,
    signature_verified   boolean NOT NULL,
    payload              jsonb NOT NULL,
    received_at          timestamptz NOT NULL DEFAULT now(),
    processed_at         timestamptz,
    processing_error     text,
    payment_link_id      bigint REFERENCES payment_links(id) ON DELETE SET NULL,
    provider_payment_id  bigint REFERENCES provider_payments(id) ON DELETE SET NULL,
    UNIQUE (provider_id, provider_event_id)
);
CREATE INDEX provider_events_unprocessed_idx ON provider_events (received_at) WHERE processed_at IS NULL;

CREATE TABLE refunds (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_payment_id   bigint REFERENCES provider_payments(id) ON DELETE RESTRICT,
    payment_id            bigint REFERENCES payments(id) ON DELETE RESTRICT,
    invoice_id            bigint REFERENCES invoices(id) ON DELETE SET NULL,
    amount                numeric(14,2) NOT NULL CHECK (amount > 0),
    currency              char(3) NOT NULL,
    reason                text,
    status                text NOT NULL DEFAULT 'requested'
                              CHECK (status IN ('requested', 'pending', 'succeeded', 'failed', 'cancelled')),
    provider_ref          text,
    requested_by          bigint REFERENCES members(id) ON DELETE SET NULL,     -- S22
    approval_request_id   bigint,                                               -- FK in 044
    processed_at          timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (provider_payment_id IS NOT NULL OR payment_id IS NOT NULL)
);
CREATE INDEX refunds_open_idx ON refunds (status) WHERE status IN ('requested', 'pending');

CREATE TABLE disputes (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_payment_id  bigint NOT NULL REFERENCES provider_payments(id) ON DELETE RESTRICT,
    provider_ref         text NOT NULL,
    amount               numeric(14,2) NOT NULL CHECK (amount > 0),
    currency             char(3) NOT NULL,
    reason               text,
    status               text NOT NULL CHECK (status IN ('needs_response', 'under_review', 'won',
                                                         'lost', 'closed')),
    evidence_due_at      timestamptz,
    opened_at            timestamptz NOT NULL DEFAULT now(),
    closed_at            timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_payment_id, provider_ref)
);
CREATE INDEX disputes_open_idx ON disputes (status) WHERE status IN ('needs_response', 'under_review');  -- S17

-- Foreign-key lookup indexes
CREATE INDEX refunds_invoice_idx ON refunds (invoice_id);
CREATE INDEX refunds_provider_payment_idx ON refunds (provider_payment_id);
CREATE INDEX refunds_payment_idx ON refunds (payment_id);

COMMIT;
