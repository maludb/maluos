"""Estate tools for the record-memory server — buildings, offices and desks.

Four tools: exactly the ones docs/business-os-mcp-tool-surface.md's "Estate: buildings,
offices, desks & the task queue" section assigns to what this slice builds (`estate`,
`locations`, `get_location`, `who_is_where`). The build spec (docs/build-specs/estate.md)
names three differently-shaped tools instead (find_locations, location_detail, estate_summary)
mapped to L1-L6, L8-L13 — but L3, L4, L5, L6, L8 and L10 need mcp_location_tasks or
mcp_consent_grants, which belong to the cross-location task queue this slice explicitly defers
to phase 6 ("Build the estate; leave the queue" / "Where [the tool-surface document] names a
tool this slice does not build, leave it unbuilt rather than stubbing it" — the build spec's
own words). Every other slice's build-spec MCP table has matched the tool-surface doc exactly
(name for name, param for param), so the mismatch here is treated as this spec's drafting
error, not a real choice — the tool-surface doc is followed, per "Parameters as
docs/business-os-mcp-tool-surface.md fixes them."

Gate: 'insider' in the tool-surface doc — matching what mcp_locations, mcp_location_residents
and mcp_applications actually enforce in SQL (WHERE app_is_insider()): any non-external member,
not the grant-scoped check ("app_can_see_locations(), grant-or-super") the build spec describes.
No such function exists in the installed schema (db/050_mcp_views_business.sql); see the
worker's escalation notes in the handback report. The PHP screens stay gated by
require_module_grant('locations') regardless, per the spec's explicit instruction.

Answers L1, L2, L9, L11, L12, L13. L3-L6, L8, L10 stay unanswered until the task queue ships
and L14 needs the prompt ledger; L7 is record_history, already built.

Reads: mcp_locations, mcp_location_residents, mcp_applications, mcp_departments,
mcp_team_directory. Registered by records_server.py; the module never opens its own connection.
"""
from __future__ import annotations

from pydantic import Field

from business_common import RO, _Base


class EstateIn(_Base):
    kind: str | None = Field(None, description="Only this kind: 'building', 'office', 'desk' or 'site' (a place the business trades from — a restaurant, a shop)")
    include_retired: bool = Field(False, description="Include retired locations")
    include_applications: bool = Field(True, description="Include what runs at each location")


class LocationsIn(_Base):
    kind: str | None = Field(None, description="'building', 'office', 'desk' or 'site'")
    parent_location_id: int | None = None
    online_only: bool = Field(False, description="Only locations currently presence = 'online'")
    siting: str | None = Field(None, description="Filter by siting: 'onsite' or 'offsite'")


class GetLocationIn(_Base):
    location_id: int


class WhoIsWhereIn(_Base):
    member_id: int | None = Field(None, description="Where this person or agent works")
    location_id: int | None = Field(None, description="Who works at this location")
    online_only: bool = Field(False, description="Only residents whose location is presence = 'online'")


def register(mcp, q) -> None:
    """Attach the estate tools; `q(sql, *args)` runs a member-scoped read."""

    # ---- estate (L11) ------------------------------------------------------
    @mcp.tool(name="estate", annotations={"title": "Estate", **RO})
    async def estate(params: EstateIn) -> str:
        """The whole picture: buildings, the offices (VMs) inside each, the desks, and what
        runs where. Call this before asking anything narrower — it is the map an agent reads
        before it asks for anything else. A building is optional: an office with no
        parent_location_id is normal, not an orphan — the minimum platform is one office plus
        one desk, and a brand-new tenant has exactly that."""
        where = ["1 = 1"]
        args: list = []
        if not params.include_retired:
            where.append("l.status = 'active'")
        if params.kind:
            args.append(params.kind)
            where.append(f"l.kind = ${len(args)}")
        locations = await q(
            f"""
            SELECT l.location_id, l.name, l.kind, l.parent_location_id, l.parent_location_name,
                   l.status, l.presence, l.last_seen_at, l.platform, l.cpu_cores, l.memory_mb,
                   l.storage_gb, l.is_always_on, l.resident_count, l.department_count,
                   l.owner_member_id, l.owner_name, l.office_manager_member_id,
                   l.siting, l.allows_agents,
                   l.operating_system, l.os_version, l.ssh_access, l.root_access,
                   l.address, l.timezone, l.resident_count, l.serving_application_count
              FROM mcp_locations l
             WHERE {' AND '.join(where)}
             ORDER BY l.kind, l.name
            """,
            *args,
        )
        if not params.include_applications:
            return '{"locations": ' + locations + '}'
        applications = await q("""
            SELECT application_id, name, category, status, location_id
              FROM mcp_applications
             WHERE location_id IS NOT NULL AND retired_at IS NULL
             ORDER BY name
        """)
        return '{"locations": ' + locations + ', "applications": ' + applications + '}'

    # ---- locations (L1, L9) -------------------------------------------------
    @mcp.tool(name="locations", annotations={"title": "Locations", **RO})
    async def locations(params: LocationsIn) -> str:
        """Locations of one kind: which desks are online, which offices exist, when each was
        last seen and what version it runs. Call for "what locations do we have", "which desks
        are online right now", "when was Ed's Desk last online and what version is it running".
        Filter by siting to separate what runs inside our own host from what is reached over
        the internet. kind='site' lists the places the business trades from (restaurants,
        shops, branches) with their address and time zone."""
        where = ["l.status = 'active'"]
        args: list = []
        if params.kind:
            args.append(params.kind)
            where.append(f"l.kind = ${len(args)}")
        if params.parent_location_id is not None:
            args.append(params.parent_location_id)
            where.append(f"l.parent_location_id = ${len(args)}")
        if params.online_only:
            where.append("l.presence = 'online'")
        if params.siting:
            args.append(params.siting)
            where.append(f"l.siting = ${len(args)}")
        return await q(
            f"""
            SELECT l.location_id, l.name, l.kind, l.parent_location_id, l.parent_location_name,
                   l.presence, l.last_seen_at, l.app_version, l.os_platform, l.mcp_surface_version,
                   l.owner_member_id, l.owner_name,
                   l.siting, l.allows_agents,
                   l.operating_system, l.os_version, l.ssh_access, l.root_access,
                   l.address, l.timezone, l.resident_count, l.serving_application_count
              FROM mcp_locations l
             WHERE {' AND '.join(where)}
             ORDER BY l.kind, l.name
             LIMIT 200
            """,
            *args,
        )

    # ---- get_location (L2, L12) ---------------------------------------------
    @mcp.tool(name="get_location", annotations={"title": "Get location", **RO})
    async def get_location(params: GetLocationIn) -> str:
        """One location's specs (platform, host reference, hostname, address, CPU, memory,
        storage), who lives there and its office manager, what it hosts, and its departments.
        A site (a restaurant, a shop) carries its address and time zone, and the applications
        serving it. Call for "what are office X's specs", "who works at the office", "what does
        it host", "who works at the Airport restaurant and what do they use there"."""
        location = await q(
            """
            SELECT l.*, td.display_name AS office_manager_name
              FROM mcp_locations l
              LEFT JOIN mcp_team_directory td ON td.member_id = l.office_manager_member_id
             WHERE l.location_id = $1
            """,
            params.location_id,
        )
        residents = await q(
            """
            SELECT member_id, member_name, member_kind, is_primary, is_office_manager
              FROM mcp_location_residents
             WHERE location_id = $1
             ORDER BY is_primary DESC, member_name
            """,
            params.location_id,
        )
        applications = await q(
            """
            SELECT application_id, name, category, status
              FROM mcp_applications
             WHERE location_id = $1 AND retired_at IS NULL
             ORDER BY name
            """,
            params.location_id,
        )
        departments = await q(
            """
            SELECT department_id, name
              FROM mcp_departments
             WHERE home_location_id = $1 AND archived_at IS NULL
             ORDER BY name
            """,
            params.location_id,
        )
        # A site runs nothing; scoped applications serve it (db/141).
        serving = await q(
            """
            SELECT application_id, application_name, scope_id, live_grant_count
              FROM mcp_application_scopes
             WHERE location_id = $1
             ORDER BY application_name
            """,
            params.location_id,
        )
        return (
            '{"location": ' + location
            + ', "residents": ' + residents
            + ', "applications": ' + applications
            + ', "serving_applications": ' + serving
            + ', "departments": ' + departments + '}'
        )

    # ---- who_is_where (L13) --------------------------------------------------
    @mcp.tool(name="who_is_where", annotations={"title": "Who is where", **RO})
    async def who_is_where(params: WhoIsWhereIn) -> str:
        """Where a person or agent works: the office an agent runs in, or who is working
        remotely from a desk right now. Call for "which office does agent X run in", "who's
        working from a desk right now", "who lives at the office"."""
        where = ["1 = 1"]
        args: list = []
        if params.member_id is not None:
            args.append(params.member_id)
            where.append(f"r.member_id = ${len(args)}")
        if params.location_id is not None:
            args.append(params.location_id)
            where.append(f"r.location_id = ${len(args)}")
        if params.online_only:
            where.append("l.presence = 'online'")
        return await q(
            f"""
            SELECT r.location_id, r.location_name, r.location_kind, r.member_id, r.member_name,
                   r.member_kind, r.is_primary, l.presence, l.last_seen_at
              FROM mcp_location_residents r
              JOIN mcp_locations l ON l.location_id = r.location_id
             WHERE {' AND '.join(where)}
             ORDER BY r.location_name, r.member_name
             LIMIT 200
            """,
            *args,
        )
