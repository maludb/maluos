-- 033_scheduling.sql
-- Scheduling & calendar (new tables; cert-study community_events stay untouched).
-- Appointments/jobs with crew (members, including agents) and bookable resources.
-- Questions: K1–K10, DB5. Recurrence is stored as an RFC 5545 RRULE and expanded by
-- the app/iCal feed; exceptions are child rows pointing at recurrence_parent_id.

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- range + scalar GiST indexes for conflict checks (K5)

CREATE TABLE appointment_types (
    id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                      text NOT NULL UNIQUE,
    default_duration_minutes  integer NOT NULL DEFAULT 60 CHECK (default_duration_minutes > 0),
    is_billable               boolean NOT NULL DEFAULT true,
    color                     text,
    department_id             bigint REFERENCES departments(id) ON DELETE SET NULL,
    archived_at               timestamptz,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bookable_resources (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    kind         text NOT NULL DEFAULT 'other' CHECK (kind IN ('room', 'vehicle', 'equipment', 'other')),
    archived_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE appointments (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_type_id   bigint REFERENCES appointment_types(id) ON DELETE SET NULL,
    title                 text NOT NULL,
    description           text,
    organization_id       bigint REFERENCES organizations(id) ON DELETE SET NULL,   -- K4, K8
    contact_id            bigint REFERENCES contacts(id) ON DELETE SET NULL,
    deal_id               bigint REFERENCES deals(id) ON DELETE SET NULL,
    project_id            bigint REFERENCES projects(id) ON DELETE SET NULL,
    task_id               bigint REFERENCES tasks(id) ON DELETE SET NULL,
    location_text         text,
    meeting_url           text,
    starts_at             timestamptz NOT NULL,
    ends_at               timestamptz NOT NULL,
    all_day               boolean NOT NULL DEFAULT false,
    timezone              text NOT NULL DEFAULT 'UTC',
    status                text NOT NULL DEFAULT 'scheduled'
                              CHECK (status IN ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show')),
    recurrence_rule       text,                                        -- RRULE
    recurrence_parent_id  bigint REFERENCES appointments(id) ON DELETE CASCADE,
    completed_at          timestamptz,                                 -- K6, K7
    cancelled_reason      text,
    owner_member_id       bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id         bigint REFERENCES departments(id) ON DELETE SET NULL,
    created_by            bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at)
);
CREATE INDEX appointments_range_idx ON appointments USING gist (tstzrange(starts_at, ends_at))
    WHERE status NOT IN ('cancelled');
CREATE INDEX appointments_starts_idx ON appointments (starts_at);
CREATE INDEX appointments_org_idx    ON appointments (organization_id, starts_at);
CREATE INDEX appointments_type_idx   ON appointments (appointment_type_id, completed_at);

-- Crew — who is booked (K1, K3, K5). Agents may be assigned for virtual duties.
CREATE TABLE appointment_assignees (
    appointment_id  bigint NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    role            text,                                              -- 'lead', 'crew'
    response        text NOT NULL DEFAULT 'pending'
                        CHECK (response IN ('pending', 'accepted', 'declined')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (appointment_id, member_id)
);
CREATE INDEX appointment_assignees_member_idx ON appointment_assignees (member_id);

CREATE TABLE appointment_resources (
    appointment_id  bigint NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    resource_id     bigint NOT NULL REFERENCES bookable_resources(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (appointment_id, resource_id)
);
CREATE INDEX appointment_resources_resource_idx ON appointment_resources (resource_id);

-- Unavailable time and working hours for people or resources (K3 "who's free").
CREATE TABLE availability_blocks (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id        bigint REFERENCES members(id) ON DELETE CASCADE,
    resource_id      bigint REFERENCES bookable_resources(id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('unavailable', 'working_hours')),
    starts_at        timestamptz NOT NULL,
    ends_at          timestamptz NOT NULL,
    recurrence_rule  text,
    note             text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at),
    CHECK ((member_id IS NOT NULL) <> (resource_id IS NOT NULL))
);
CREATE INDEX availability_member_idx   ON availability_blocks USING gist (member_id, tstzrange(starts_at, ends_at));
CREATE INDEX availability_resource_idx ON availability_blocks USING gist (resource_id, tstzrange(starts_at, ends_at));

-- Foreign-key lookup indexes
CREATE INDEX appointments_project_idx ON appointments (project_id);
CREATE INDEX appointments_deal_idx ON appointments (deal_id);
CREATE INDEX appointments_contact_idx ON appointments (contact_id);
CREATE INDEX appointments_task_idx ON appointments (task_id);
CREATE INDEX appointments_parent_idx ON appointments (recurrence_parent_id);
CREATE INDEX appointments_owner_idx ON appointments (owner_member_id);

COMMIT;
