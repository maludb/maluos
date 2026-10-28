-- 005_study_log.sql
-- Study Session — a member studied on a date (plan §3.1). Powers weak-domains (M4),
-- study-time-by-domain (M10), and at-risk detection (O2). §8.6: owner + organizers only.
-- resource_id FK is added in 008_resources.sql.

BEGIN;

CREATE TABLE study_sessions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id      bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    attempt_id     bigint REFERENCES exam_attempts(id) ON DELETE SET NULL,
    exam_id        bigint REFERENCES exams(id) ON DELETE SET NULL,       -- denormalized for per-exam rollups
    domain_id      bigint REFERENCES exam_domains(id) ON DELETE SET NULL,
    resource_id    bigint,                                 -- FK added in 008_resources.sql
    studied_on     date   NOT NULL,
    minutes        integer NOT NULL CHECK (minutes > 0 AND minutes <= 1440),
    confidence     smallint CHECK (confidence BETWEEN 1 AND 5),          -- confidence after (1–5)
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX study_sessions_member_date_idx ON study_sessions (member_id, studied_on DESC);
CREATE INDEX study_sessions_domain_idx      ON study_sessions (domain_id);
CREATE INDEX study_sessions_exam_idx        ON study_sessions (exam_id);
CREATE INDEX study_sessions_resource_idx    ON study_sessions (resource_id);  -- passers' resource usage (O11)

COMMIT;
