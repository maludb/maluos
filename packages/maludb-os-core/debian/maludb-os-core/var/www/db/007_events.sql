-- 007_events.sql
-- Community Event + Event RSVP (plan §3.1). The calendar's event layer is a view over
-- scheduled events (010 defines the calendar view). §8.1: any member can create an
-- event; organizers can edit/cancel any (enforced in RLS 011). §8.3: no recurrence —
-- a "duplicate event" action copies the row to a new date.

BEGIN;

CREATE TABLE community_events (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    host_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind          text   NOT NULL
                     CHECK (kind IN ('study_group','workshop','office_hours','mock_exam','social')),
    title         text   NOT NULL,
    description   text,
    -- Events are timestamptz and render in the viewer's timezone (§7).
    starts_at     timestamptz NOT NULL,
    ends_at       timestamptz,
    is_online     boolean NOT NULL DEFAULT true,
    meeting_url   text,                                    -- when online
    location      text,                                    -- when in person
    exam_id       bigint REFERENCES exams(id) ON DELETE SET NULL,
    domain_id     bigint REFERENCES exam_domains(id) ON DELETE SET NULL,
    capacity      integer CHECK (capacity IS NULL OR capacity > 0),
    status        text   NOT NULL DEFAULT 'scheduled'
                     CHECK (status IN ('scheduled','cancelled')),
    cancelled_reason text,
    duplicated_from_event_id bigint REFERENCES community_events(id) ON DELETE SET NULL,  -- §8.3

    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT event_ends_after_starts CHECK (ends_at IS NULL OR ends_at >= starts_at)
);
CREATE INDEX events_starts_idx     ON community_events (starts_at) WHERE status = 'scheduled';
CREATE INDEX events_exam_idx       ON community_events (exam_id);
CREATE INDEX events_host_idx       ON community_events (host_id);   -- "events hosted" contribution (O6)

-- --------------------------------------------------------------------------
-- Event RSVP — updated in place; changes go to the activity log
-- --------------------------------------------------------------------------
CREATE TABLE event_rsvps (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id    bigint NOT NULL REFERENCES community_events(id) ON DELETE CASCADE,
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    response    text   NOT NULL CHECK (response IN ('going','maybe','not_going')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, member_id)
);
CREATE INDEX rsvps_event_idx  ON event_rsvps (event_id, response);   -- "who's coming" (M12), draw counts (O10)
CREATE INDEX rsvps_member_idx ON event_rsvps (member_id);

COMMIT;
