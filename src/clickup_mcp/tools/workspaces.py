import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_workspaces() -> str:
        """Get all ClickUp workspaces (teams) accessible with the current token."""
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get("/team")
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_list_members(team_id: str | None = None) -> str:
        """List ClickUp workspace members, flattened to id/username/email/team_id/role.

        Use this to resolve a person (by email) to the ClickUp user_id that
        clickup_search_tasks/clickup_list_tasks_for_person's `assignees`
        param expects. Reads the same GET /team endpoint clickup_get_workspaces
        uses, so it needs no extra permissions — this tool just projects the
        member list to a flat, purpose-built shape instead of leaving callers
        to dig it out of the full workspace/team object.

        Args:
            team_id: Optional workspace/team ID to filter to. Omit to return
                members across every workspace visible to this token.

        Returns JSON: { members: [ { user_id, username, email, team_id,
        role } ] }. `role` is ClickUp's role_key (e.g. "owner", "admin",
        "member", "guest").

        Known gap: there is no reliable "is this member deactivated" field
        on ClickUp's team-member object (the only `status` field present,
        `invited_by.status`, describes the inviter, not the member) — an
        `active` field was requested but is not included here since nothing
        real backs it; do not assume every returned member is still active.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get("/team")
        except ClickUpError as e:
            return f"Error: {e}"
        teams = (result or {}).get("teams", []) or []
        members: list[dict] = []
        for team in teams:
            tid = team.get("id")
            if team_id is not None and str(tid) != str(team_id):
                continue
            for m in team.get("members", []) or []:
                user = m.get("user", m)
                user_id = user.get("id")
                members.append(
                    {
                        "user_id": str(user_id) if user_id is not None else None,
                        "username": user.get("username"),
                        "email": user.get("email"),
                        "team_id": str(tid) if tid is not None else None,
                        "role": user.get("role_key"),
                    }
                )
        return json.dumps({"members": members}, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def clickup_list_spaces(team_id: str, archived: bool = False) -> str:
        """List all spaces in a ClickUp workspace.

        Args:
            team_id: The workspace/team ID.
            archived: Include archived spaces (default: False).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/team/{team_id}/space", {"archived": archived})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
