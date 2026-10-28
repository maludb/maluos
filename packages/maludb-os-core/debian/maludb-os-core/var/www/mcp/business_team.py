"""Team & access — read tools (docs/business-os-mcp-tool-surface.md).

Reads: mcp_business_invitations. Every query runs as the asking member, so the view decides what
comes back: a super-admin sees every pending invitation, a dept-admin those into departments
they administer, anyone else none. Writing (send, resend, revoke) is the actions server's job.
"""
from __future__ import annotations

from business_common import RO, _Base


class TeamInvitationsIn(_Base):
    pass


def register(mcp, q) -> None:
    # The tool surface (A3, A10) names this `team_invitations` with an optional status of
    # pending/all. mcp_business_invitations holds pending invitations only, so that is what this
    # answers; "all" waits for a view that carries accepted and revoked ones.
    @mcp.tool(name="team_invitations", annotations={"title": "Team invitations", **RO})
    async def team_invitations(params: TeamInvitationsIn) -> str:
        """Who has been invited and has not yet accepted: the address, what they will be
        (user, dept_admin or super_admin), who invited them, when, and whether the link has
        expired. Call for "who have we invited", "has Priya accepted her invitation", "which
        invitations have expired". Accepted and revoked invitations are not listed. To act on
        one, pass its invitation_id to invitation_resend or invitation_revoke (actions server)."""
        return await q(
            """
            SELECT invitation_id, email, business_role_granted, invited_by_name,
                   created_at, expires_at, expires_at < now() AS expired
              FROM mcp_business_invitations
             ORDER BY created_at DESC
             LIMIT 200
            """
        )
