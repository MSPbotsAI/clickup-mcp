from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_workspaces() -> str:
        """Get all ClickUp workspaces (teams) accessible with the current token.

        Returns each workspace's id/name/color/avatar. ClickUp's native
        response also embeds a full member list per team; that is stripped
        out here to keep the response small. To resolve a person to a
        user_id, use clickup_list_members instead.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/team")
            if isinstance(result, dict):
                for team in result.get("teams", []) or []:
                    team.pop("members", None)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_list_members(
        team_id: Annotated[
            str | None,
            Field(description="Optional workspace/team ID to filter to. Omit for every workspace."),
        ] = None,
    ) -> str:
        """List ClickUp workspace members, flattened to id/username/email/team_id/role.

        Use this to resolve a person (by email) to the user_id that
        clickup_search_tasks/clickup_list_tasks_for_person's `assignees` param
        expects.

        Returns JSON: { members: [ { user_id, username, email, team_id, role } ] }.
        `role` is ClickUp's role_key (owner/admin/member/guest). Known gap: no
        reliable "deactivated" field exists — don't assume every member is active.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/team")
        except ClickUpError as e:
            return e.to_envelope()
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
        return dump_json_capped({"members": members})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_list_spaces(
        team_id: Annotated[str, Field(description="The workspace/team ID.")],
        archived: Annotated[bool, Field(description="Include archived spaces.")] = False,
    ) -> str:
        """List all spaces in a ClickUp workspace."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/team/{team_id}/space", {"archived": archived})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
