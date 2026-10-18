-- 008_resources.sql
-- Resource + Resource Endorsement (plan §3.1). A resource covers many exams/domains
-- (join tables). M13/O11 rank resources by endorsements from certified members and by
-- how often passers' plan items and study sessions reference them.
-- This file also wires the deferred resource_id FKs from plan_items, study_sessions,
-- and replies (declared bigint there, constrained here — resources didn't exist yet).

BEGIN;

CREATE TABLE resources (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submitted_by  bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    title         text   NOT NULL,
    url           text   NOT NULL,
    type          text   NOT NULL
                     CHECK (type IN ('official_guide','docs','course','practice_exam','video','article','repo')),
    description   text,

    hidden_at     timestamptz,
    hidden_by     bigint REFERENCES members(id) ON DELETE SET NULL,
    hidden_reason text,

    search_tsv    tsvector,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX resources_type_idx   ON resources (type) WHERE hidden_at IS NULL;
CREATE INDEX resources_search_idx ON resources USING gin (search_tsv);

CREATE OR REPLACE FUNCTION resources_tsv_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title,'')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description,'')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER resources_tsv_trg BEFORE INSERT OR UPDATE OF title, description
    ON resources FOR EACH ROW EXECUTE FUNCTION resources_tsv_update();

-- Coverage: a resource applies to exams and/or specific domains (filter M13/O11).
CREATE TABLE resource_exams (
    resource_id bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    exam_id     bigint NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    PRIMARY KEY (resource_id, exam_id)
);
CREATE TABLE resource_domains (
    resource_id bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    domain_id   bigint NOT NULL REFERENCES exam_domains(id) ON DELETE CASCADE,
    PRIMARY KEY (resource_id, domain_id)
);
CREATE INDEX resource_domains_domain_idx ON resource_domains (domain_id);

-- Endorsement — a member marks a resource helpful. Ranking weights endorsements from
-- certified members higher (M13); the "certified" test is a view (011/records MCP).
CREATE TABLE resource_endorsements (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resource_id  bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    member_id    bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (resource_id, member_id)
);
CREATE INDEX resource_endorsements_resource_idx ON resource_endorsements (resource_id);

-- --------------------------------------------------------------------------
-- Deferred FKs: plan_items / study_sessions / replies -> resources
-- --------------------------------------------------------------------------
ALTER TABLE plan_items
    ADD CONSTRAINT plan_items_resource_fk
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE SET NULL;
ALTER TABLE study_sessions
    ADD CONSTRAINT study_sessions_resource_fk
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE SET NULL;
ALTER TABLE replies
    ADD CONSTRAINT replies_resource_fk
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE SET NULL;

COMMIT;
