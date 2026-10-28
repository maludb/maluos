-- 003_attempts.sql
-- Exam Attempt — a member's intent to sit an exam, from first idea to result.
-- The calendar's exam layer is a VIEW over this table (plan §3.1). A retake is a new
-- attempt; a renewal is a new attempt with kind='renewal'. Reschedules edit the date
-- in place; the before/after goes to the activity log (M17) — no reschedule table.

BEGIN;

CREATE TABLE exam_attempts (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    exam_id         bigint NOT NULL REFERENCES exams(id) ON DELETE RESTRICT,

    kind            text NOT NULL DEFAULT 'exam'
                        CHECK (kind IN ('exam', 'renewal')),
    status          text NOT NULL DEFAULT 'considering'
                        CHECK (status IN ('considering','scheduled','taken','passed','not_passed','withdrawn')),

    -- Scheduling. exam_date required once scheduled (enforced below). Stored as a local
    -- date + time + the member's tz at the time (attempts are local, not timestamptz — §7).
    exam_date       date,
    start_time      time,                                  -- optional, member's local time
    timezone        text,                                  -- IANA tz captured when scheduled
    delivery        text CHECK (delivery IN ('online','test_center')),
    date_is_tentative boolean NOT NULL DEFAULT false,

    -- Visibility (D6-adjacent; plan §3.2)
    calendar_visible boolean NOT NULL DEFAULT true,        -- §8.5: visible by default, hideable
    result_shared    boolean NOT NULL DEFAULT false,       -- D3: private by default

    -- Result (recorded when status -> passed/not_passed). No score is ever stored (D3).
    result_recorded_at timestamptz,
    certified_on       date,                               -- set on pass
    certified_until    date,                               -- = certified_on + exam.validity_months, fixed at record time

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    -- A scheduled/taken/result attempt must carry a date.
    CONSTRAINT attempt_date_required
        CHECK (status = 'considering' OR status = 'withdrawn' OR exam_date IS NOT NULL),
    -- A passed attempt carries its certification window.
    CONSTRAINT attempt_pass_dates
        CHECK (status <> 'passed' OR (certified_on IS NOT NULL AND certified_until IS NOT NULL))
);
CREATE INDEX attempts_member_idx      ON exam_attempts (member_id);
CREATE INDEX attempts_exam_date_idx   ON exam_attempts (exam_id, exam_date);
CREATE INDEX attempts_calendar_idx    ON exam_attempts (exam_date)
    WHERE calendar_visible AND status IN ('scheduled','taken','passed','not_passed');
-- Certified-members / expiry queries (M6, M9, M14, O9, O11)
CREATE INDEX attempts_cert_idx        ON exam_attempts (exam_id, certified_until)
    WHERE status = 'passed';

COMMIT;
