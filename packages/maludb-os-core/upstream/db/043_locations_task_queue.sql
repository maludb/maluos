-- 043_locations_task_queue.sql
-- The estate: where work happens. A location tree of buildings (a Proxmox host or a
-- physical site), offices (the VMs inside a building — one per department cluster), and
-- desks (one per enrolled desktop). Plus residents (human or agent) per location, desk
-- consent, and the server task queue that brokers every cross-location request (never
-- peer-to-peer). Applications that run at a location are in 055.
-- Questions: L1–L14, DC8, PL9. agent_run_id FK added in 045.

BEGIN;

CREATE TABLE locations (
    id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                       text NOT NULL UNIQUE,                 -- 'HQ', 'Office — Finance', "Ed's Desk"
    kind                       text NOT NULL CHECK (kind IN ('building', 'office', 'desk')),
    parent_location_id         bigint REFERENCES locations(id) ON DELETE RESTRICT,  -- office -> building
    description                text,
    owner_member_id            bigint REFERENCES members(id) ON DELETE RESTRICT,   -- desk owner
    office_manager_member_id   bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL,
    status                     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    presence                   text NOT NULL DEFAULT 'unknown' CHECK (presence IN ('online', 'offline', 'unknown')),
    last_seen_at               timestamptz,                          -- L9
    -- Infrastructure facts (L11, L12): a building is the hypervisor host, an office is a VM
    -- on it, a desk is a workstation. Same columns describe all three.
    platform                   text CHECK (platform IN ('proxmox', 'kvm', 'lxc', 'bare_metal',
                                                        'cloud', 'workstation', 'other')),
    external_ref               text,                                 -- Proxmox node name or VMID
    hostname                   text,
    ip_address                 inet,
    cpu_cores                  integer CHECK (cpu_cores > 0),
    memory_mb                  integer CHECK (memory_mb > 0),
    storage_gb                 integer CHECK (storage_gb > 0),
    is_always_on               boolean NOT NULL DEFAULT false,       -- offices yes, desks no
    app_version                text,
    os_platform                text,                                 -- 'windows', 'macos', 'linux'
    mcp_surface_version        text,
    enrollment_token_id        bigint REFERENCES mcp_access_tokens(id) ON DELETE SET NULL,
    enrolled_at                timestamptz,
    retired_at                 timestamptz,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT locations_desk_has_owner CHECK (kind <> 'desk' OR owner_member_id IS NOT NULL),
    CONSTRAINT locations_building_is_root CHECK (kind <> 'building' OR parent_location_id IS NULL)
);
CREATE INDEX locations_owner_idx  ON locations (owner_member_id);
CREATE INDEX locations_parent_idx ON locations (parent_location_id);
CREATE INDEX locations_kind_idx   ON locations (kind, status);

CREATE TABLE location_residents (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id      bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    member_id        bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,  -- human or agent (L2, L13)
    is_primary       boolean NOT NULL DEFAULT true,   -- false = also works here (remote/visiting)
    added_at         timestamptz NOT NULL DEFAULT now(),
    removed_at       timestamptz
);
CREATE UNIQUE INDEX location_residents_live_idx ON location_residents (location_id, member_id)
    WHERE removed_at IS NULL;

-- Desk owner's permission for others to send tasks to the desk (L6, L7).
CREATE TABLE consent_grants (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    desk_location_id      bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    grantee_member_id     bigint REFERENCES members(id) ON DELETE CASCADE,     -- null = anyone in tenant
    grantee_location_id   bigint REFERENCES locations(id) ON DELETE CASCADE,
    task_type             text,                                              -- null = any task type
    scope                 text NOT NULL CHECK (scope IN ('standing', 'one_off')),
    granted_by            bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    expires_at            timestamptz,
    used_at               timestamptz,                                       -- one_off consumed
    revoked_at            timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX consent_grants_desk_idx ON consent_grants (desk_location_id) WHERE revoked_at IS NULL;

-- The server task queue: requester -> server -> target location's office manager -> agent.
CREATE TABLE location_tasks (
    id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requester_member_id       bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    requester_location_id     bigint REFERENCES locations(id) ON DELETE SET NULL,
    target_location_id        bigint NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    assigned_agent_member_id  bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL,  -- L10
    task_type                 text NOT NULL,
    title                     text NOT NULL,
    instructions              text NOT NULL,
    input_ref                 jsonb NOT NULL DEFAULT '{}',          -- record refs / opted-in local paths
    priority                  text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status                    text NOT NULL DEFAULT 'queued'
                                  CHECK (status IN ('queued', 'awaiting_consent', 'delivered', 'running',
                                                    'done', 'failed', 'refused', 'cancelled', 'expired')),
    consent_grant_id          bigint REFERENCES consent_grants(id) ON DELETE SET NULL,
    result_summary            text,
    result_ref                jsonb,
    refused_reason            text,                                  -- L5
    failure_reason            text,
    entity_type               text,
    entity_id                 bigint,
    agent_run_id              bigint,                                -- FK in 045
    queued_at                 timestamptz NOT NULL DEFAULT now(),
    delivered_at              timestamptz,                           -- L8 wait = delivered - queued
    started_at                timestamptz,
    finished_at               timestamptz,
    expires_at                timestamptz,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX location_tasks_target_idx    ON location_tasks (target_location_id, status);   -- L4
CREATE INDEX location_tasks_requester_idx ON location_tasks (requester_member_id, queued_at DESC);  -- L3
CREATE INDEX location_tasks_problem_idx   ON location_tasks (finished_at DESC) WHERE status IN ('failed', 'refused');

ALTER TABLE departments
    ADD CONSTRAINT departments_home_location_fk
    FOREIGN KEY (home_location_id) REFERENCES locations(id) ON DELETE SET NULL;
CREATE INDEX departments_home_location_idx ON departments (home_location_id);
ALTER TABLE agent_profiles
    ADD CONSTRAINT agent_profiles_home_location_fk
    FOREIGN KEY (home_location_id) REFERENCES locations(id) ON DELETE SET NULL;
ALTER TABLE agent_duties
    ADD CONSTRAINT agent_duties_location_fk
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL;
ALTER TABLE documents
    ADD CONSTRAINT documents_origin_location_fk
    FOREIGN KEY (origin_location_id) REFERENCES locations(id) ON DELETE SET NULL;

-- Foreign-key lookup indexes
CREATE INDEX location_residents_member_idx ON location_residents (member_id);
CREATE INDEX consent_grants_grantee_idx ON consent_grants (grantee_member_id);
CREATE INDEX location_tasks_agent_idx ON location_tasks (assigned_agent_member_id, status);

COMMIT;
