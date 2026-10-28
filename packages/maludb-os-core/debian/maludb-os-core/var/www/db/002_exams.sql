-- 002_exams.sql
-- Community settings (singleton, D1) + the exam catalog + weighted domains.
-- Maintained by organizers (plan §3.1, §3.3). Seed data lives in 020_seed_exams.sql.

BEGIN;

-- --------------------------------------------------------------------------
-- Community settings — one row (D1: single community, no tenant table)
-- --------------------------------------------------------------------------
CREATE TABLE community_settings (
    id                  boolean PRIMARY KEY DEFAULT true CHECK (id),  -- enforces a single row
    community_name      text NOT NULL DEFAULT 'MaluDB OS',
    timezone            text NOT NULL DEFAULT 'UTC',                  -- default display tz for community events

    -- Retake policy (plan §3.3) — editable without a schema change.
    -- Wait days keyed by prior-fail count: 1st retake waits [0], 2nd [1], 3rd [2]...
    retake_wait_days    integer[] NOT NULL DEFAULT '{14,30,90}',
    max_attempts_per_12mo integer NOT NULL DEFAULT 4 CHECK (max_attempts_per_12mo > 0),

    -- Study-buddy window (M2): "same exam within N days of my date"
    study_buddy_window_days integer NOT NULL DEFAULT 14 CHECK (study_buddy_window_days > 0),
    -- At-risk thresholds (O2): no study logged in N days
    at_risk_no_study_days   integer NOT NULL DEFAULT 14 CHECK (at_risk_no_study_days > 0),

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
INSERT INTO community_settings (id) VALUES (true) ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------------------
-- Exam — a certification in the catalog
-- --------------------------------------------------------------------------
CREATE TABLE exams (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code              text NOT NULL UNIQUE,                -- 'CCAO-F', 'CCDV-F', 'CCAR-F', 'CCAR-P'
    name              text NOT NULL,
    audience          text,                                -- 'Associate' / 'Developer' / 'Architect' ...
    description       text,
    official_guide_url text,
    guide_version     text,                                -- e.g. 'v1.0 July 2026'
    duration_minutes  integer NOT NULL DEFAULT 120 CHECK (duration_minutes > 0),
    question_count    integer CHECK (question_count IS NULL OR question_count > 0),
    passing_score     integer NOT NULL DEFAULT 720,        -- of 1000, informational only (D3)
    validity_months   integer NOT NULL DEFAULT 12 CHECK (validity_months > 0),
    sort_order        integer NOT NULL DEFAULT 0,
    active            boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX exams_active_idx ON exams (active, sort_order);

-- --------------------------------------------------------------------------
-- Exam Domain — a weighted topic area within an exam
-- --------------------------------------------------------------------------
CREATE TABLE exam_domains (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exam_id     bigint NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    name        text   NOT NULL,
    weight      numeric(5,2) NOT NULL CHECK (weight >= 0 AND weight <= 100),  -- percent
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (exam_id, name)
);
CREATE INDEX exam_domains_exam_idx ON exam_domains (exam_id, sort_order);

COMMIT;
