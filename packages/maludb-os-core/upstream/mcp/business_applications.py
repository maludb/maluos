"""Applications tools for the record-memory server — the technical asset registry.

Five tools: the ones docs/business-os-mcp-tool-surface.md's Applications row assigns
(find_applications, get_application, my_applications, answering AC1-AC5) and, since db/141,
application_scopes and member_application_access for scoped applications. Gate: 'insider' for
find_applications and get_application (mcp_applications / mcp_application_endpoints are both
gated on app_is_insider() in SQL); get_application's access list narrows further in SQL
(mcp_application_access: applications module grant, super-admin, or the grantee's own row/
department) — this file does not re-implement that, it just returns what the view gives.
my_applications is 'all' (own grants) per the tool-surface doc.

db/075 made this registry the single source of truth for every MCP server an agent can use:
agent_tool_grants.application_endpoint_id points at application_endpoints, so an application
registered here with an agent-reachable, active MCP endpoint is immediately what
my_applications and get_application describe to an agent deciding what to reach for.

No secret is ever selected — mcp_application_endpoints exposes has_credential, a boolean, never
secret_id or a value.

Registered by records_server.py; the module never opens its own connection.
"""
from __future__ import annotations

from pydantic import Field

from business_common import RO, _Base


class FindApplicationsIn(_Base):
    category: str | None = Field(
        None,
        description="platform, accounting, crm, calendar, email, documents, storage, database, "
                    "communication, automation, development, security, other",
    )
    department_id: int | None = Field(None, description="Only applications owned by this department")
    location_id: int | None = Field(None, description="Only applications running at this location")
    health: str | None = Field(None, description="'up', 'degraded', 'down' or 'unknown'")
    business_area: str | None = Field(
        None,
        description="Only this business area, by name: Everyday, Sales & Service, Finance, Operations, "
                    "Human Resources, Administration, Technology & Infrastructure",
    )
    expert_agent_member_id: int | None = Field(None, description="Only applications this agent is the expert on")
    gaps_only: bool = Field(
        False,
        description="Only applications with a gap: no owner department, no health check in the "
                    "last 30 days, a live endpoint whose auth_kind is not 'none' and has no "
                    "credential attached, or an expert who has no access to the application",
    )
    include_available: bool = Field(
        False,
        description="Also list, under 'available', what the business could run and does not: "
                    "catalog entries no registered application carries",
    )


class GetApplicationIn(_Base):
    application_id: int
    include_access: bool = Field(
        False,
        description="Include who has access and at what capability — further gated in SQL: the "
                    "applications module grant, super-admin, or a grantee sees their own row",
    )


class MyApplicationsIn(_Base):
    category: str | None = None


class ApplicationScopesIn(_Base):
    application_id: int = Field(..., description="The application (a scoped one serves several sites or departments)")
    scope_id: int | None = Field(None, description="Only this scope (one site or department it serves)")


class MemberApplicationAccessIn(_Base):
    member_id: int = Field(..., description="The member — a person or an agent")
    application_id: int | None = Field(None, description="Only this application")


def register(mcp, q) -> None:
    """Attach the applications tools; `q(sql, *args)` runs a member-scoped read."""

    # ---- find_applications (AC1, AC4) ---------------------------------------
    @mcp.tool(name="find_applications", annotations={"title": "Find applications", **RO})
    async def find_applications(params: FindApplicationsIn) -> str:
        """What we run and where: by category, department or office, by health, and the gaps —
        no owner department, a stale health check, or an endpoint that needs a credential it
        has not got. Every application sits in a business area and may name an expert: the agent
        to ask about it (sme_agent_member_id / sme_agent_name). Call for "what do we run", "what's
        in the storage category", "what has no owner", "what needs attention", "who is the expert
        on Books", "what is Sasha the expert on", "what could we run in Finance that we don't"
        (include_available)."""
        where = ["1 = 1"]
        args: list = []
        if params.category:
            args.append(params.category)
            where.append(f"a.category = ${len(args)}")
        if params.department_id is not None:
            args.append(params.department_id)
            where.append(f"a.owner_department_id = ${len(args)}")
        if params.location_id is not None:
            args.append(params.location_id)
            where.append(f"a.location_id = ${len(args)}")
        if params.health:
            args.append(params.health)
            where.append(f"a.health_status = ${len(args)}")
        if params.business_area:
            args.append("" if params.business_area.strip().lower() == "everyday" else params.business_area.strip())
            where.append(f"lower(a.business_area_name) = lower(${len(args)})")
        if params.expert_agent_member_id is not None:
            args.append(params.expert_agent_member_id)
            where.append(f"a.sme_agent_member_id = ${len(args)}")
        if params.gaps_only:
            where.append("""(a.owner_department_id IS NULL
                OR a.last_health_check_at IS NULL
                OR a.last_health_check_at < now() - interval '30 days'
                OR EXISTS (SELECT 1 FROM mcp_application_endpoints e
                            WHERE e.application_id = a.application_id
                              AND e.auth_kind <> 'none' AND e.has_credential = false)
                OR (a.sme_agent_member_id IS NOT NULL AND a.status IN ('active', 'degraded')
                    AND NOT (a.application_id = ANY (app_member_application_ids(a.sme_agent_member_id)))))""")
        applications = await q(
            f"""
            SELECT a.application_id, a.name, a.app_key, a.category, a.is_builtin, a.module,
                   a.location_id, a.location_name, a.owner_department_id, a.owner_department_name,
                   a.owner_member_id, a.owner_name, a.criticality, a.status, a.health_status,
                   a.last_health_check_at, a.i_can_use,
                   CASE WHEN a.business_area_name = '' THEN 'Everyday' ELSE a.business_area_name END AS business_area,
                   a.module_enabled, a.sme_agent_member_id, a.sme_agent_name,
                   (SELECT count(*) FROM mcp_skill_assignments s WHERE s.application_id = a.application_id) AS skill_count
              FROM mcp_applications a
             WHERE {' AND '.join(where)}
             ORDER BY a.name
             LIMIT 200
            """,
            *args,
        )
        if not params.include_available:
            return applications
        area = None if not params.business_area else (
            "" if params.business_area.strip().lower() == "everyday" else params.business_area.strip())
        available = await q(
            """
            SELECT c.catalog_key, c.name, c.description, c.kind, c.vendor,
                   CASE WHEN c.business_area_name = '' THEN 'Everyday' ELSE c.business_area_name END AS business_area
              FROM mcp_application_catalog c
             WHERE NOT EXISTS (SELECT 1 FROM mcp_applications a
                                WHERE a.catalog_key = c.catalog_key AND a.status <> 'retired')
               AND ($1::text IS NULL OR lower(c.business_area_name) = lower($1))
             ORDER BY c.business_area_sort, c.sort_order, c.name
            """,
            area,
        )
        return '{"applications": ' + applications + ', "available": ' + available + '}'

    # ---- get_application (AC1, AC3, AC5) ------------------------------------
    @mcp.tool(name="get_application", annotations={"title": "Get application", **RO})
    async def get_application(params: GetApplicationIn) -> str:
        """One application: where it runs, who owns it, its endpoints (kind, url, auth_kind,
        has_credential — never the credential itself — agent_reachable, mcp_surface_version),
        who has access at what capability, what it costs (its linked recurring expense, if
        any), its business area, its expert agent and the skills that belong to it. Call for
        "tell me about the CRM", "what endpoints does X have", "who can use X", "what does X
        cost", "who is the expert on X", "what skills come with X"."""
        application = await q(
            "SELECT * FROM mcp_applications WHERE application_id = $1", params.application_id
        )
        endpoints = await q(
            """
            SELECT application_endpoint_id, name, kind, url, auth_kind, has_credential,
                   agent_reachable, mcp_surface_version, status
              FROM mcp_application_endpoints
             WHERE application_id = $1
             ORDER BY name
            """,
            params.application_id,
        )
        # The cost link went with Expenses in the kernel cut (db/133); the key stays, empty.
        cost = "[]"
        skills = await q(
            """
            SELECT skill_assignment_id, skill_name, pinned_bundle_hash, note, created_at
              FROM mcp_skill_assignments
             WHERE application_id = $1
             ORDER BY skill_name
            """,
            params.application_id,
        )
        # What one installation serves and its own roles (db/141).
        roles = await q(
            """
            SELECT role_key, name, capability, is_admin, live_grant_count
              FROM mcp_application_roles WHERE application_id = $1 ORDER BY sort_order, application_role_id
            """,
            params.application_id,
        )
        scopes = await q(
            """
            SELECT scope_id, location_id, department_id, scope_name, address, timezone, live_grant_count
              FROM mcp_application_scopes WHERE application_id = $1 ORDER BY scope_name
            """,
            params.application_id,
        )
        if not params.include_access:
            return (
                '{"application": ' + application
                + ', "endpoints": ' + endpoints
                + ', "cost": ' + cost
                + ', "skills": ' + skills
                + ', "roles": ' + roles
                + ', "scopes": ' + scopes + '}'
            )
        access = await q(
            """
            SELECT application_access_id, member_id, member_name, department_id, department_name,
                   resident_location_id, resident_location_name, scope_id, scope_name, role_key, role_name,
                   capability, granted_by, granted_at, expires_at
              FROM mcp_application_access
             WHERE application_id = $1
             ORDER BY granted_at DESC
            """,
            params.application_id,
        )
        return (
            '{"application": ' + application
            + ', "endpoints": ' + endpoints
            + ', "cost": ' + cost
            + ', "skills": ' + skills
            + ', "roles": ' + roles
            + ', "scopes": ' + scopes
            + ', "access": ' + access + '}'
        )

    # ---- my_applications (AC2) -----------------------------------------------
    @mcp.tool(name="my_applications", annotations={"title": "My applications", **RO})
    async def my_applications(params: MyApplicationsIn) -> str:
        """What I can reach and how — the first call an agent makes when a job needs an outside
        system: the endpoint it would actually use (url, kind, mcp_surface_version), and the
        capability it holds; is_default marks the one app.<domain> opens after sign-in (db/142).
        Never a credential."""
        where = ["1 = 1"]
        args: list = []
        if params.category:
            args.append(params.category)
            where.append(f"a.category = ${len(args)}")
        applications = await q(
            f"""
            SELECT a.application_id, a.name, a.app_key, a.category, a.is_builtin, a.module,
                   a.location_id, a.location_name, a.url, a.status, a.health_status,
                   a.capability, a.endpoint_count,
                   (a.application_id = app_my_default_application_id()) IS TRUE AS is_default
              FROM mcp_my_applications a
             WHERE {' AND '.join(where)}
             ORDER BY a.name
             LIMIT 200
            """,
            *args,
        )
        return '{"applications": ' + applications + '}'

    # ---- application_scopes (db/141) -----------------------------------------
    @mcp.tool(name="application_scopes", annotations={"title": "Application scopes", **RO})
    async def application_scopes(params: ApplicationScopesIn) -> str:
        """The sites or departments one installation of a scoped application serves (each
        restaurant of Reservations, each department's plans in a project tool), and on each who
        is granted what: the grantee (a member, a department, or everyone residing at a site),
        the application's own role and the capability it amounts to. The grants are further
        gated in SQL as get_application's access list is. Call for "which restaurants does
        Reservations serve", "who is a manager at Airport in Reservations", "who can use it at
        Downtown"."""
        scopes = await q(
            """
            SELECT scope_id, application_id, application_name, scope_kind, location_id, department_id,
                   scope_name, address, timezone, live_grant_count, added_at
              FROM mcp_application_scopes
             WHERE application_id = $1 AND ($2::bigint IS NULL OR scope_id = $2)
             ORDER BY scope_name
            """,
            params.application_id, params.scope_id,
        )
        grants = await q(
            """
            SELECT application_access_id, scope_id, scope_name, member_id, member_name, department_id,
                   department_name, resident_location_id, resident_location_name, role_key, role_name,
                   capability, granted_at, expires_at
              FROM mcp_application_access
             WHERE application_id = $1 AND scope_id IS NOT NULL AND ($2::bigint IS NULL OR scope_id = $2)
             ORDER BY scope_name, role_name, member_name, department_name
            """,
            params.application_id, params.scope_id,
        )
        return '{"scopes": ' + scopes + ', "grants": ' + grants + '}'

    # ---- member_application_access (db/141) ----------------------------------
    @mcp.tool(name="member_application_access", annotations={"title": "Member application access", **RO})
    async def member_application_access(params: MemberApplicationAccessIn) -> str:
        """Every application a member (a person or an agent) can use, and where: each grant that
        reaches them — directly, through a department they belong to, or through a site or
        office they reside at — with its scope (site or department), the application's own role
        and the capability. Gated in SQL as get_application's access list is. Call for "what can
        Maria use, and where", "which restaurants is Sam a manager at", "why can Priya open
        Reservations"."""
        return await q(
            """
            SELECT ac.application_id, ac.application_name, ac.scope_id, ac.scope_name, ac.role_key,
                   ac.role_name, ac.capability, ac.expires_at,
                   CASE WHEN ac.member_id IS NOT NULL THEN 'member'
                        WHEN ac.department_id IS NOT NULL THEN 'department: ' || ac.department_name
                        ELSE 'residents: ' || ac.resident_location_name END AS route
              FROM mcp_application_access ac
             WHERE ($2::bigint IS NULL OR ac.application_id = $2)
               AND (ac.member_id = $1
                    OR ac.department_id IN (SELECT department_id FROM mcp_department_members
                                             WHERE member_id = $1 AND left_at IS NULL)
                    OR ac.resident_location_id IN (SELECT location_id FROM mcp_location_residents
                                                    WHERE member_id = $1))
             ORDER BY ac.application_name, ac.scope_name
             LIMIT 200
            """,
            params.member_id, params.application_id,
        )
