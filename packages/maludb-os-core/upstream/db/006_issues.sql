-- 006_issues.sql
-- Study Issue + Reply (plan §3.1). Postgres full-text search over issues and replies
-- answers M5 ("has anyone been stuck on what I'm stuck on?"). resource_id on replies
-- FK'd in 008_resources.sql.

BEGIN;

-- --------------------------------------------------------------------------
-- Study Issue — something a member is stuck on
-- --------------------------------------------------------------------------
CREATE TABLE study_issues (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    author_id      bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    exam_id        bigint REFERENCES exams(id) ON DELETE SET NULL,
    domain_id      bigint REFERENCES exam_domains(id) ON DELETE SET NULL,
    title          text   NOT NULL,
    body           text   NOT NULL,                        -- markdown
    status         text   NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','resolved')),
    accepted_reply_id bigint,                              -- FK added after replies table below

    -- Moderation (organizer hides; audit goes to activity log — O15)
    hidden_at      timestamptz,
    hidden_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    hidden_reason  text,

    -- Full-text search vector (title weighted 'A', body 'B'), maintained by trigger.
    search_tsv     tsvector,

    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX issues_exam_domain_idx ON study_issues (exam_id, domain_id, status);
CREATE INDEX issues_status_idx      ON study_issues (status) WHERE hidden_at IS NULL;
CREATE INDEX issues_author_idx      ON study_issues (author_id);
CREATE INDEX issues_search_idx      ON study_issues USING gin (search_tsv);

-- --------------------------------------------------------------------------
-- Reply — a response on an issue
-- --------------------------------------------------------------------------
CREATE TABLE replies (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    issue_id       bigint NOT NULL REFERENCES study_issues(id) ON DELETE CASCADE,
    author_id      bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    body           text   NOT NULL,
    resource_id    bigint,                                 -- FK added in 008_resources.sql

    hidden_at      timestamptz,
    hidden_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    hidden_reason  text,

    search_tsv     tsvector,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX replies_issue_idx  ON replies (issue_id, created_at);
CREATE INDEX replies_author_idx ON replies (author_id);      -- "accepted answers" contribution (O6)
CREATE INDEX replies_search_idx ON replies USING gin (search_tsv);

-- accepted_reply_id FK now that replies exists
ALTER TABLE study_issues
    ADD CONSTRAINT issues_accepted_reply_fk
    FOREIGN KEY (accepted_reply_id) REFERENCES replies(id) ON DELETE SET NULL;

-- --------------------------------------------------------------------------
-- Full-text search vector maintenance
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION issues_tsv_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title,'')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.body,'')),  'B');
    RETURN NEW;
END$$;
CREATE TRIGGER issues_tsv_trg BEFORE INSERT OR UPDATE OF title, body
    ON study_issues FOR EACH ROW EXECUTE FUNCTION issues_tsv_update();

CREATE OR REPLACE FUNCTION replies_tsv_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv := to_tsvector('english', coalesce(NEW.body,''));
    RETURN NEW;
END$$;
CREATE TRIGGER replies_tsv_trg BEFORE INSERT OR UPDATE OF body
    ON replies FOR EACH ROW EXECUTE FUNCTION replies_tsv_update();

COMMIT;
