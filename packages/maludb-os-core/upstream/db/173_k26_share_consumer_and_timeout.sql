-- 173: K26 — a K7 provider is told who is asking, and a share may ask for a longer call (owner approved 2026-10-06;
-- docs/build-specs/kernel-app-services.md "K26"). Additive.
--
-- The identity travels in two HTTP headers on the kernel's MCP call (X-OS-Consumer: the consumer application's
-- catalog key; X-OS-Consumer-Agent: the member id of its expert agent, absent when it has none) — never in the
-- arguments, because the providers validate a share's arguments strictly (extra = forbid) and a consumer-supplied
-- identity must never reach a provider. This file adds the one column the timeout needs: the seconds the kernel
-- waits for a share's answer, from the provider's maludb-os.json shares[].timeout_seconds (default 8, at most 60).
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/173_k26_share_consumer_and_timeout.sql

ALTER TABLE application_shares
    ADD COLUMN timeout_seconds smallint NOT NULL DEFAULT 8 CHECK (timeout_seconds BETWEEN 1 AND 60);
COMMENT ON COLUMN application_shares.timeout_seconds IS 'K26 (db/173): how long the kernel waits for this share''s answer — the provider''s shares[].timeout_seconds, 1–60, default 8.';
