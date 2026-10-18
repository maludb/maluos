-- 113: People (docs/build-specs/people.md). ADDITIVE.
--
-- db/058 says agents never see people data; nothing said an agent cannot BE an employee. An
-- agent on a pay run or holding a leave balance is a category error, so the database refuses
-- the employment record itself. No rows exist yet, so nothing is invalidated.
BEGIN;

CREATE OR REPLACE FUNCTION employment_profiles_humans_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT member_kind FROM members WHERE id = NEW.member_id) <> 'human' THEN
        RAISE EXCEPTION 'An agent is not an employee: employment, pay and leave are for people.'
            USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS employment_profiles_humans_only ON employment_profiles;
CREATE TRIGGER employment_profiles_humans_only BEFORE INSERT OR UPDATE OF member_id ON employment_profiles
    FOR EACH ROW EXECUTE FUNCTION employment_profiles_humans_only();

COMMIT;
