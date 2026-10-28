-- 044_approvals.sql
-- Approval thresholds + the manager approval queue. An action matching an active policy
-- pauses as an approval request; on approval the app executes it and links the resulting
-- activity_log row (executed_activity_id), which is what makes AP8/SM13 provable.
-- Default thresholds are still an open question (proposed: money out, deletions, external
-- sends for agents). Policies are seeded with the action manifest (build plan 1.6), since
-- action_pattern must match real manifest action keys.
-- Questions: AP1–AP8, S22, SM3, SM13, H8. agent_run_id FK added in 045.

BEGIN;

CREATE TABLE approval_policies (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                text NOT NULL,
    category            text NOT NULL CHECK (category IN ('money_out', 'deletion', 'external_send', 'other')),
    action_pattern      text NOT NULL,                     -- manifest action key or 'prefix.*'
    applies_to          text NOT NULL DEFAULT 'agents'
                            CHECK (applies_to IN ('agents', 'agent', 'department', 'everyone')),
    agent_member_id     bigint REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    department_id       bigint REFERENCES departments(id) ON DELETE CASCADE,
    amount_threshold    numeric(14,2) CHECK (amount_threshold >= 0),   -- null = always
    currency            char(3),
    approver_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,   -- null = requester's manager
    expires_after_hours integer NOT NULL DEFAULT 72 CHECK (expires_after_hours > 0),
    active              boolean NOT NULL DEFAULT true,
    created_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (applies_to <> 'agent' OR agent_member_id IS NOT NULL),
    CHECK (applies_to <> 'department' OR department_id IS NOT NULL),
    CHECK (amount_threshold IS NULL OR currency IS NOT NULL)
);
CREATE INDEX approval_policies_active_idx ON approval_policies (action_pattern) WHERE active;

CREATE TABLE approval_requests (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    policy_id              bigint REFERENCES approval_policies(id) ON DELETE SET NULL,
    requested_by_member_id bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    agent_run_id           bigint,                                  -- FK in 045
    action_key             text NOT NULL,                           -- manifest action
    parameters             jsonb NOT NULL DEFAULT '{}',
    summary                text NOT NULL,                           -- human-readable "Send invoice INV-00042"
    amount                 numeric(14,2),
    currency               char(3),
    entity_type            text,
    entity_id              bigint,
    approver_member_id     bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    status                 text NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending', 'approved', 'rejected', 'expired',
                                                 'cancelled', 'executed', 'execution_failed')),
    decided_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    decided_at             timestamptz,                             -- AP6 = decided_at - created_at
    decision_note          text,
    expires_at             timestamptz NOT NULL,
    executed_at            timestamptz,
    executed_activity_id   bigint,                                  -- activity_log.id; no FK so log archival stays free
    execution_error        text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX approval_requests_queue_idx     ON approval_requests (approver_member_id, created_at)
    WHERE status = 'pending';                                        -- AP1
CREATE INDEX approval_requests_requester_idx ON approval_requests (requested_by_member_id, created_at DESC);
CREATE INDEX approval_requests_decider_idx   ON approval_requests (decided_by, decided_at DESC);
CREATE INDEX approval_requests_entity_idx    ON approval_requests (entity_type, entity_id);

ALTER TABLE refunds
    ADD CONSTRAINT refunds_approval_request_fk
    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id) ON DELETE RESTRICT;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_approval_request_fk
    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id) ON DELETE RESTRICT;
ALTER TABLE content_items
    ADD CONSTRAINT content_items_approval_request_fk
    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id) ON DELETE RESTRICT;
ALTER TABLE agent_escalations
    ADD CONSTRAINT agent_escalations_approval_request_fk
    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id) ON DELETE SET NULL;

-- Foreign-key lookup indexes
CREATE INDEX approval_requests_policy_idx ON approval_requests (policy_id);
CREATE INDEX refunds_approval_idx ON refunds (approval_request_id);
CREATE INDEX expenses_approval_idx ON expenses (approval_request_id);
CREATE INDEX content_items_approval_idx ON content_items (approval_request_id);

COMMIT;
