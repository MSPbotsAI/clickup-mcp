import json
from collections.abc import Callable
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."

# ClickUp's "Filter Team Tasks" endpoint (GET /team/:team_id/task) paginates
# 100 tasks per page and gives no total-count/last-page field — the documented
# convention is: keep incrementing `page` until a page comes back with fewer
# than 100 tasks. See https://clickup.com/api docs, "Get Filtered Team Tasks".
_CLICKUP_PAGE_SIZE = 100
_MAX_PAGES_PER_WORKSPACE = 20  # paranoid safety net; real loops stop far earlier


def _iso_to_ms(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_iso(ms_value) -> str | None:
    if not ms_value:
        return None
    try:
        return (
            datetime.fromtimestamp(int(ms_value) / 1000, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError):
        return None


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


def _project_task(task: dict, team_id: str, space_names: dict[str, str]) -> dict:
    status = task.get("status") or {}
    priority = task.get("priority") or {}
    space = task.get("space") or {}
    list_obj = task.get("list") or {}
    space_id = space.get("id")
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "status": status.get("status"),
        "status_type": status.get("type"),
        "priority": priority.get("priority") if isinstance(priority, dict) else None,
        "due_date": _ms_to_iso(task.get("due_date")),
        "date_closed": _ms_to_iso(task.get("date_closed")),
        "url": task.get("url"),
        "list_name": list_obj.get("name"),
        "space_name": space_names.get(space_id),
        "team_id": team_id,
    }


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_list_tasks_for_person(
        email: str | None = None,
        user_id: str | None = None,
        include_closed: bool = False,
        updated_since: str | None = None,
        limit: int = 200,
    ) -> str:
        """List a person's tasks across every ClickUp workspace visible to this
        token, in one call — a "fat tool" wrapper around clickup_search_tasks
        for the common "what's on this person's plate" use case.

        Unlike clickup_search_tasks, team_id is NOT required: this tool
        discovers every workspace the token can see and merges results across
        all of them, resolving email -> user_id internally when needed. This
        is its whole value over calling clickup_search_tasks directly.

        Args:
            email: The person's ClickUp email. Provide this OR user_id (at
                least one required). Matched case-insensitively against each
                workspace's member list.
            user_id: The person's ClickUp user ID, if already known. Skips
                the email lookup.
            include_closed: Include completed/closed tasks. Default False —
                only open/incomplete tasks are returned.
            updated_since: ISO-8601 UTC timestamp (e.g.
                "2026-08-01T00:00:00Z"). Only tasks updated at or after this
                time are returned — use for incremental/delta pulls.
            limit: Max tasks to return across all workspaces combined.
                Default 200, hard cap 500 (values above 500 are clamped).

        Returns JSON: { tasks: [...], truncated: bool, resolved_user_id: str }.
        Each task has id/name/status/status_type/priority/due_date/
        date_closed/url/list_name/space_name/team_id. status_type is
        ClickUp's status-type enum (open/custom/closed/done) — the only
        reliable way to tell whether a custom-named status counts as done.
        due_date/date_closed are ISO-8601 UTC strings, or null if unset
        (never 0 — a raw 0 would misread as an 1970 due date).
        `truncated: true` means limit was hit or a workspace's task list ran
        past the safety-cap page count — results are a partial view, not
        silently cut off without you knowing.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        if not email and not user_id:
            return "Error: provide at least one of 'email' or 'user_id'"

        if limit > 500:
            limit = 500
        elif limit < 1:
            limit = 1

        try:
            team_result = await client.get("/team")
        except ClickUpError as e:
            return f"Error: {e}"
        teams = (team_result or {}).get("teams", []) or []

        resolved_user_id = user_id
        if not resolved_user_id:
            resolved_user_id = _find_user_id_by_email(teams, email)
            if not resolved_user_id:
                return (
                    f"Error: no ClickUp member found with email '{email}' in any "
                    "workspace visible to this token"
                )

        date_updated_gt = None
        if updated_since:
            try:
                date_updated_gt = _iso_to_ms(updated_since)
            except ValueError:
                return f"Error: could not parse 'updated_since' as ISO-8601: {updated_since}"

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
            space_names: dict[str, str] = {}
            try:
                space_result = await client.get(f"/team/{team_id}/space", {"archived": False})
                for sp in (space_result or {}).get("spaces", []) or []:
                    if sp.get("id"):
                        space_names[sp["id"]] = sp.get("name")
            except ClickUpError:
                pass  # non-fatal — space_name just stays null for this workspace

            page = 0
            while page < _MAX_PAGES_PER_WORKSPACE:
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
                    return f"Error: {e}"

                page_tasks = (result or {}).get("tasks", []) or []
                if not page_tasks:
                    break

                for t in page_tasks:
                    if len(all_tasks) >= limit:
                        truncated = True
                        break
                    all_tasks.append(_project_task(t, team_id, space_names))

                if len(page_tasks) < _CLICKUP_PAGE_SIZE:
                    break  # last page for this workspace, per ClickUp's convention
                page += 1
            else:
                truncated = True  # hit _MAX_PAGES_PER_WORKSPACE without exhausting

        return json.dumps(
            {
                "tasks": all_tasks,
                "truncated": truncated,
                "resolved_user_id": resolved_user_id,
            },
            indent=2,
            ensure_ascii=False,
        )
