-- 001_auth.sql
-- Authentication + identity. The php-session-auth schema (Google identity + TOTP 2FA
-- + recovery codes) ships in full even before the features are switched on.
--
-- The memory-model entity is "Member" (plan §3.1). We name the auth+profile table
-- `members` and it plays the php-session-auth `users` role: auth_identities,
-- totp_recovery_codes, and every owning FK across the app reference members(id).
-- One identity space keeps RLS (keyed on app.member_id) clean.

BEGIN;

-- --------------------------------------------------------------------------
-- Member (auth anchor + community profile)
-- --------------------------------------------------------------------------
CREATE TABLE members (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email               citext NOT NULL UNIQUE,           -- normalized (lower/trim) in the app too
    password_hash       text,                             -- NULLABLE: Google-only accounts have none
    email_verified_at   timestamptz,                      -- null = unverified

    -- 2FA (TOTP). Secret encrypted at rest (libsodium secretbox, key in env).
    totp_secret         text,
    totp_enabled_at     timestamptz,                      -- null = 2FA off
    totp_last_timestep  bigint,                           -- replay guard

    -- Community profile (plan §3.1)
    display_name        text NOT NULL,
    timezone            text NOT NULL DEFAULT 'UTC',       -- IANA name, e.g. 'America/Chicago'
    bio                 text,
    organization        text,
    role                text NOT NULL DEFAULT 'member'
                            CHECK (role IN ('member', 'organizer')),

    -- Notification preferences (which emails the app sends this member)
    notify_reply        boolean NOT NULL DEFAULT true,     -- reply on my issue / comment on my plan
    notify_event        boolean NOT NULL DEFAULT true,     -- event changed / cancelled / reminder
    notify_exam         boolean NOT NULL DEFAULT true,     -- exam in 7 days / cert expiring
    notify_digest       boolean NOT NULL DEFAULT true,     -- "what changed since last login"

    status              text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended')),
    last_login_at       timestamptz,
    joined_at           timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX members_role_idx        ON members (role);
CREATE INDEX members_display_trgm    ON members USING gin (display_name gin_trgm_ops);

-- --------------------------------------------------------------------------
-- Federated identities (Sign in with Google, OIDC)
-- --------------------------------------------------------------------------
CREATE TABLE auth_identities (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    provider          text   NOT NULL,                    -- 'google'
    provider_user_id  text   NOT NULL,                    -- Google's stable 'sub' claim
    email_at_provider text   NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);
CREATE INDEX auth_identities_member_idx ON auth_identities (member_id);

-- --------------------------------------------------------------------------
-- TOTP recovery codes (10 single-use, stored hashed)
-- --------------------------------------------------------------------------
CREATE TABLE totp_recovery_codes (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id  bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    code_hash  text   NOT NULL,                            -- password_hash() of the code
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX totp_recovery_member_idx ON totp_recovery_codes (member_id) WHERE used_at IS NULL;

-- --------------------------------------------------------------------------
-- Password reset + email verification tokens (hashed, single-use, expiring)
-- --------------------------------------------------------------------------
CREATE TABLE password_reset_tokens (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_hash  text   NOT NULL UNIQUE,                    -- sha256 of the emailed token
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_reset_member_idx ON password_reset_tokens (member_id);

CREATE TABLE email_verification_tokens (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_hash  text   NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Login attempt log (brute-force lockout, per-account AND per-IP)
-- --------------------------------------------------------------------------
CREATE TABLE login_attempts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email       citext,                                    -- attempted email (may not exist)
    ip_address  inet   NOT NULL,
    successful  boolean NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_email_time_idx ON login_attempts (email, attempted_at DESC);
CREATE INDEX login_attempts_ip_time_idx    ON login_attempts (ip_address, attempted_at DESC);

-- --------------------------------------------------------------------------
-- Invitation (invite-only registration, plan §3.1; §8.2: organizers only)
-- --------------------------------------------------------------------------
-- Registration (password OR Google) succeeds only against a valid, unexpired,
-- unrevoked invitation for that email. Organizer-only creation is enforced by RLS
-- (011) and the controller, not by this table's shape.
CREATE TABLE invitations (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email          citext NOT NULL,
    role_granted   text   NOT NULL DEFAULT 'member'
                        CHECK (role_granted IN ('member', 'organizer')),
    invited_by     bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    personal_message text,
    token_hash     text   NOT NULL UNIQUE,                 -- sha256 of the emailed token
    expires_at     timestamptz NOT NULL,
    accepted_at    timestamptz,
    accepted_member_id bigint REFERENCES members(id) ON DELETE SET NULL,
    revoked_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
-- At most one live (pending, unexpired-at-creation, unrevoked) invite per email.
CREATE UNIQUE INDEX invitations_live_email_idx ON invitations (email)
    WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX invitations_inviter_idx ON invitations (invited_by);

COMMIT;
