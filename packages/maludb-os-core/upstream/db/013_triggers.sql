-- 013_triggers.sql
-- Shared updated_at maintenance. Every table with an updated_at column gets a BEFORE
-- UPDATE trigger that stamps now().

BEGIN;

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'members','invitations','community_settings','exams','exam_domains',
        'exam_attempts','study_plans','plan_items','plan_comments','study_sessions',
        'study_issues','replies','community_events','event_rsvps','resources'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
            t || '_touch', t);
    END LOOP;
END$$;

COMMIT;
