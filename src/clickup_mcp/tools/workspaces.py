from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN
from ._teams import (
    annotate,
    pick_team_ids,
    resolve_team_scope,
    summarize_teams,
    team_error_envelope,
)


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
            Field(
                description=(
                    "Workspace/team ID to filter to. Optional — resolved from the API "
                    "token, and every accessible workspace is included when omitted."
                )
            ),
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
        raw_teams = (result or {}).get("teams", []) or []
        # Check the filter against what the token can actually see: a team_id the
        # token has no access to should return the legal set, not an empty list
        # that reads as "this workspace has no members".
        scope = pick_team_ids(summarize_teams(raw_teams), team_id)
        if scope.error:
            return scope.error
        wanted = set(scope.team_ids)
        members: list[dict] = []
        for team in raw_teams:
            tid = team.get("id")
            if str(tid) not in wanted:
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
        return dump_json_capped(annotate({"members": members}, scope))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_list_spaces(
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID. Optional — resolved from the API token, and "
                    "every accessible workspace is listed when omitted."
                )
            ),
        ] = None,
        archived: Annotated[bool, Field(description="Include archived spaces.")] = False,
    ) -> str:
        """List all spaces in a ClickUp workspace."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        scope = await resolve_team_scope(client, team_id)
        if scope.error:
            return scope.error

        if len(scope.team_ids) == 1:
            target = scope.team_ids[0]
            try:
                result = await client.get(f"/team/{target}/space", {"archived": archived})
            except ClickUpError as e:
                return team_error_envelope(e, scope.teams, target)
            if isinstance(result, dict):
                result["team_id"] = target
            return dump_json_capped(annotate(result, scope))

        names = {team["id"]: team.get("name") for team in scope.teams}
        spaces: list[dict] = []
        for target in scope.team_ids:
            try:
                result = await client.get(f"/team/{target}/space", {"archived": archived})
            except ClickUpError as e:
                return team_error_envelope(e, scope.teams, target)
            for space in (result or {}).get("spaces", []) or []:
                space["team_id"] = target
                space["team_name"] = names.get(target)
                spaces.append(space)
        return dump_json_capped({"spaces": spaces, "searched_workspaces": scope.teams})
