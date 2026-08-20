from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ClickUpClient, ClickUpError
from ._common import (
    CLICKUP_PAGE_SIZE,
    MAX_PAGES_PER_WORKSPACE,
    MAX_TASKS,
    NO_TOKEN,
    fetch_space_names,
    project_task,
)


def _iso_to_ms(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _find_user_id_by_email(teams: list[dict], email: str) -> str | None:
    target = email.strip().lower()
    for team in teams:
        for member in team.get("members", []) or []:
            # Tolerate both ClickUp's native nested shape ({"user": {...}})
            # and an already-flattened one ({"id", "email", ...}).
            user = member.get("user", member)
            member_email = (user.get("email") or "").strip().lower()
            if member_email == target:
                user_id = user.get("id")
                return str(user_id) if user_id is not None else None
    return None


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_list_tasks_for_person(
        email: Annotated[
            str | None,
            Field(
                description=(
                    "The person's ClickUp email. Provide this OR user_id (at least "
                    "one required). Matched case-insensitively against each "
                    "workspace's member list."
                )
            ),
        ] = None,
        user_id: Annotated[
            str | None,
            Field(description="The person's ClickUp user ID, if already known. Skips the email lookup."),
        ] = None,
        include_closed: Annotated[
            bool,
            Field(description="Include completed/closed tasks. Only open/incomplete tasks otherwise."),
        ] = False,
        updated_since: Annotated[
            str | None,
            Field(
                description=(
                    'ISO-8601 UTC timestamp (e.g. "2026-08-01T00:00:00Z"). Only tasks '
                    "updated at or after this time are returned — use for incremental pulls."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Max tasks to return across all workspaces combined (1-200)."),
        ] = 200,
    ) -> str:
        """List a person's tasks across every ClickUp workspace visible to this
        token, wrapping clickup_search_tasks for "what's on this person's plate".

        Returns JSON: { tasks: [...], truncated: bool, resolved_user_id }. Each task has
        id/name/status/status_type/priority/due_date/date_closed/url/list_name/space_name/team_id.
        `truncated: true` means limit hit or a workspace ran past the safety cap.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if not email and not user_id:
            return error_envelope(
                "invalid_argument", "provide at least one of 'email' or 'user_id'", False
            )

        if limit > MAX_TASKS:
            limit = MAX_TASKS
        elif limit < 1:
            limit = 1

        try:
            team_result = await client.get("/team")
        except ClickUpError as e:
            return e.to_envelope()
        teams = (team_result or {}).get("teams", []) or []

        resolved_user_id = user_id
        if not resolved_user_id:
            resolved_user_id = _find_user_id_by_email(teams, email)
            if not resolved_user_id:
                return error_envelope(
                    "not_found",
                    f"no ClickUp member found with email '{email}' in any workspace visible to this token",
                    False,
                )

        date_updated_gt = None
        if updated_since:
            try:
                date_updated_gt = _iso_to_ms(updated_since)
            except ValueError:
                return error_envelope(
                    "invalid_argument",
                    f"could not parse 'updated_since' as ISO-8601: {updated_since}",
                    False,
                )

        all_tasks: list[dict] = []
        truncated = False

        for team in teams:
            if len(all_tasks) >= limit:
                truncated = True
                break

            team_id = team.get("id")
            if not team_id:
                continue

            # Task objects from the search endpoint carry space.id but not
            # space.name — resolve it once per workspace via the space list.
            space_names = await fetch_space_names(client, team_id)

            page = 0
            while page < MAX_PAGES_PER_WORKSPACE:
                if len(all_tasks) >= limit:
                    truncated = True
                    break

                params: dict = {
                    "page": page,
                    "assignees[]": [resolved_user_id],
                    "include_closed": include_closed,
                }
                if date_updated_gt is not None:
                    params["date_updated_gt"] = date_updated_gt

                try:
                    result = await client.get(f"/team/{team_id}/task", params)
                except ClickUpError as e:
                    return e.to_envelope()

                page_tasks = (result or {}).get("tasks", []) or []
                if not page_tasks:
                    break

                for t in page_tasks:
                    if len(all_tasks) >= limit:
                        truncated = True
                        break
                    all_tasks.append(project_task(t, team_id, space_names))

                if len(page_tasks) < CLICKUP_PAGE_SIZE:
                    break  # last page for this workspace, per ClickUp's convention
                page += 1
            else:
                truncated = True  # hit MAX_PAGES_PER_WORKSPACE without exhausting

        return dump_json_capped(
            {
                "tasks": all_tasks,
                "truncated": truncated,
                "resolved_user_id": resolved_user_id,
            }
        )
