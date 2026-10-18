-- 004_plans.sql
-- Study Plan + Plan Items + Plan Comments (plan §3.1).
-- Copying a plan copies its items with due dates shifted to the new exam date (O7);
-- copied_from_plan_id records the lineage. Resources referenced by plan items are
-- created in 008_resources.sql, so plan_items.resource_id is added there (FK-after).

BEGIN;

-- --------------------------------------------------------------------------
-- Study Plan
-- --------------------------------------------------------------------------
CREATE TABLE study_plans (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    attempt_id        bigint REFERENCES exam_attempts(id) ON DELETE SET NULL,  -- the attempt this plan targets
    exam_id           bigint NOT NULL REFERENCES exams(id) ON DELETE RESTRICT, -- denormalized for filtering when attempt is null
    title             text NOT NULL,
    approach          text,                                -- markdown
    visibility        text NOT NULL DEFAULT 'community'
                          CHECK (visibility IN ('community','private')),   -- D6
    status            text NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','archived')),
    copied_from_plan_id bigint REFERENCES study_plans(id) ON DELETE SET NULL,  -- O7
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX plans_member_idx    ON study_plans (member_id);
CREATE INDEX plans_exam_idx      ON study_plans (exam_id, visibility, status);
CREATE INDEX plans_copied_idx    ON study_plans (copied_from_plan_id);  -- "which plans get copied most" (O7)

-- --------------------------------------------------------------------------
-- Plan Item — one milestone. "On track" (M3) = completed vs. due-by-today.
-- --------------------------------------------------------------------------
CREATE TABLE plan_items (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id        bigint NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    domain_id      bigint REFERENCES exam_domains(id) ON DELETE SET NULL,
    title          text   NOT NULL,
    notes          text,
    due_date       date,
    resource_id    bigint,                                 -- FK added in 008_resources.sql
    sort_order     integer NOT NULL DEFAULT 0,
    completed_at   timestamptz,                            -- null = open
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX plan_items_plan_idx     ON plan_items (plan_id, sort_order);
CREATE INDEX plan_items_domain_idx   ON plan_items (domain_id);
CREATE INDEX plan_items_resource_idx ON plan_items (resource_id);  -- top-resources-in-passers-plans (O11)

-- --------------------------------------------------------------------------
-- Plan Comment — feedback on a community-visible plan (M8)
-- --------------------------------------------------------------------------
CREATE TABLE plan_comments (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id     bigint NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    author_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    body        text   NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX plan_comments_plan_idx ON plan_comments (plan_id, created_at);

COMMIT;
