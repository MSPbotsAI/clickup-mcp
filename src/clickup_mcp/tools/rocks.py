import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ClickUpClient, ClickUpError
from ._common import CLICKUP_PAGE_SIZE, NO_TOKEN

# Same pagination convention as clickup_search_tasks / clickup_list_tasks_for_person:
# ClickUp's list-scoped "Get Tasks" endpoint (GET /list/:list_id/task) returns up
# to 100 tasks per page with no total-count/last-page field — stop once a page
# comes back with fewer than 100.
_MAX_PAGES_PER_LIST = 20  # paranoid safety net

# EOS Rocks in this ClickUp workspace turned out to live as regular tasks in a
# list literally named "Rocks" (found under Space "Company" > Folder
# "EOS Traction", but discovered dynamically below rather than hardcoded, in
# case the org restructures spaces/folders later — the list *name* convention
# is the stable contract, not its current location). Confirmed 2026-08-18 by
# inspecting a real rock task's fields directly via the ClickUp API.
_ROCKS_LIST_NAME = "rocks"

# Rock-specific custom fields observed on real rock tasks, matched by name
# (case-insensitive) since custom field IDs are workspace-specific and every
# task also carries a pile of unrelated workspace-wide custom fields
# (Timesheet Project, BASELINE_*, etc.) that must be ignored.
_FIELD_QUARTER = "quarter"
_FIELD_ROCKS_STATUS = "rocks status"
_FIELD_ROCK_TYPE = "rock type"
_FIELD_DEPARTMENT = "department"
_FIELD_PROGRESS_MANUAL = "progress"
_FIELD_PROGRESS_AUTO = "progress %"

# ClickUp's "Rocks Status" dropdown has 6 options; our contract only has 5
# (on_track/off_track/done/missed/open). This mapping is a judgment call,
# not a 1:1 translation — "missed" is never emitted here since nothing in
# ClickUp's data models "ran out of time without finishing" as distinct from
# "off track"; deriving that from due_date-passed would be a business-logic
# assumption we haven't confirmed, so we don't guess at it.
_STATUS_MAP = {
    "on track": "on_track",
    "off track": "off_track",
    "completed": "done",
    "blocked": "off_track",
    "at risk": "off_track",
    "on hold": "open",
}


def _quarter_field_to_iso(label: str | None) -> str | None:
    """Convert ClickUp's "Q3 2026" dropdown option label to our "2026-Q3"."""
    if not label:
        return None
    parts = label.strip().split()
    if len(parts) != 2:
        return None
    q, year = parts
    return f"{year}-{q}"


def _iso_quarter_to_field_label(iso_quarter: str) -> str | None:
    """Convert "2026-Q3" back to ClickUp's "Q3 2026" label, for filtering."""
    parts = iso_quarter.strip().split("-")
    if len(parts) != 2:
        return None
    year, q = parts
    return f"{q} {year}"


def _current_iso_quarter() -> str:
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def _dropdown_value(field: dict) -> str | None:
    """Resolve a drop_down custom field's numeric `value` (an orderindex) to
    its option label. Returns None if unset or unresolvable."""
    value = field.get("value")
    if value is None:
        return None
    options = field.get("type_config", {}).get("options", []) or []
    for opt in options:
        if opt.get("orderindex") == value:
            return opt.get("name")
    return None


def _progress_percent(fields_by_name: dict[str, dict]) -> float | None:
    auto = fields_by_name.get(_FIELD_PROGRESS_AUTO)
    if auto and isinstance(auto.get("value"), dict):
        pct = auto["value"].get("percent_complete")
        if pct is not None:
            return pct
    manual = fields_by_name.get(_FIELD_PROGRESS_MANUAL)
    if manual and isinstance(manual.get("value"), dict):
        pct = manual["value"].get("percent_completed")
        if pct is not None:
            return pct
    return None


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


def _project_rock(task: dict) -> dict:
    fields_by_name = {
        (f.get("name") or "").strip().lower(): f for f in (task.get("custom_fields") or [])
    }

    quarter_label = _dropdown_value(fields_by_name.get(_FIELD_QUARTER, {})) if _FIELD_QUARTER in fields_by_name else None
    status_label = _dropdown_value(fields_by_name.get(_FIELD_ROCKS_STATUS, {})) if _FIELD_ROCKS_STATUS in fields_by_name else None
    rock_type = _dropdown_value(fields_by_name.get(_FIELD_ROCK_TYPE, {})) if _FIELD_ROCK_TYPE in fields_by_name else None
    department = _dropdown_value(fields_by_name.get(_FIELD_DEPARTMENT, {})) if _FIELD_DEPARTMENT in fields_by_name else None

    assignees = task.get("assignees") or []
    owner = assignees[0] if assignees else {}

    description = (task.get("text_content") or task.get("description") or "").strip()

    return {
        "id": task.get("id"),
        "title": task.get("name"),
        # No dedicated "measurable" field exists on this list — best-effort
        # fallback to the task description per explicit instruction; null if
        # the description is empty (never fabricated).
        "measurable": description or None,
        "quarter": _quarter_field_to_iso(quarter_label),
        "owner_email": owner.get("email"),
        "owner_user_id": str(owner["id"]) if owner.get("id") is not None else None,
        "owner_name": owner.get("username"),
        "progress_percent": _progress_percent(fields_by_name),
        "status": _STATUS_MAP.get((status_label or "").strip().lower(), "open"),
        # The raw ClickUp status label (e.g. "At Risk"), alongside the
        # normalized 5-value `status` above. Consumers branch on `status`;
        # this is purely so a UI can show ClickUp's own wording instead of
        # ours, so the two don't visibly disagree. Additive, no behaviour
        # change to the existing `status` field.
        "status_raw": status_label,
        "rock_type": rock_type,
        "department": department,
        "due_date": _ms_to_iso(task.get("due_date")),
        "url": task.get("url"),
        # No structured weekly on/off tracking field was found anywhere on a
        # real rock task (not a custom field, not comments-derived here) —
        # left empty rather than fabricated. Revisit if the org starts
        # tracking this in ClickUp some other way.
        "weekly_status": [],
    }


async def _spaces_for_team(client: ClickUpClient, team_id: str) -> list[dict]:
    try:
        space_result = await client.get(f"/team/{team_id}/space", {"archived": False})
    except ClickUpError:
        return []
    return (space_result or {}).get("spaces", []) or []


async def _rocks_lists_in_space(client: ClickUpClient, space_id: str) -> list[dict]:
    async def _folderless() -> list[dict]:
        try:
            r = await client.get(f"/space/{space_id}/list", {"archived": False})
        except ClickUpError:
            return []
        return (r or {}).get("lists", []) or []

    async def _folders() -> list[dict]:
        try:
            r = await client.get(f"/space/{space_id}/folder", {"archived": False})
        except ClickUpError:
            return []
        return (r or {}).get("folders", []) or []

    folderless_lists, folders = await asyncio.gather(_folderless(), _folders())

    found: list[dict] = [
        lst for lst in folderless_lists if (lst.get("name") or "").strip().lower() == _ROCKS_LIST_NAME
    ]
    for folder in folders:
        found.extend(
            lst
            for lst in folder.get("lists", []) or []
            if (lst.get("name") or "").strip().lower() == _ROCKS_LIST_NAME
        )
    return found


async def _find_rocks_lists(client: ClickUpClient) -> list[dict]:
    """Discover every list literally named "Rocks" (case-insensitive) across
    every workspace/space this token can see, folder or folderless.

    Every space's lookup runs concurrently (asyncio.gather), not one after
    another — a sequential version of this walk was measured to time out
    against MSPbots' own workspace (15+ spaces x 2 calls each, run one at a
    time, comfortably exceeded the caller's MCP timeout). ClickUp's rate
    limit is a per-minute budget with no separate burst cap (100/min on the
    lowest plan tier), and this fires on the order of 2 x (space count)
    requests once, so a few dozen concurrent calls stays well inside it.
    """
    try:
        team_result = await client.get("/team")
    except ClickUpError:
        return []
    teams = (team_result or {}).get("teams", []) or []
    team_ids = [team.get("id") for team in teams if team.get("id")]

    space_lists = await asyncio.gather(*(_spaces_for_team(client, tid) for tid in team_ids))
    space_ids = [
        space.get("id")
        for spaces in space_lists
        for space in spaces
        if space.get("id")
    ]

    per_space_results = await asyncio.gather(
        *(_rocks_lists_in_space(client, sid) for sid in space_ids)
    )
    return [lst for lists in per_space_results for lst in lists]


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_list_rocks_for_org(
        quarter: Annotated[
            str | None,
            Field(
                description=(
                    'Target quarter as "YYYY-Qn", e.g. "2026-Q3". Defaults to the '
                    "current UTC quarter if omitted."
                )
            ),
        ] = None,
        include_completed: Annotated[
            bool,
            Field(
                description=(
                    "Include rocks already marked Completed. Default True — quarterly "
                    "reviews usually want to see what finished, not just what's outstanding."
                )
            ),
        ] = True,
        owner_email: Annotated[
            str | None,
            Field(
                description=(
                    "Optional — restrict results to rocks owned by this person's email "
                    "(matched case-insensitively against the rock's first assignee). "
                    "Omit for the default org-wide behavior (every rock, from every "
                    "owner). Filtering happens after the org-wide fetch, so this saves "
                    "response size for a single-person view but not upstream API calls."
                )
            ),
        ] = None,
        owner_user_id: Annotated[
            str | None,
            Field(
                description=(
                    "Optional — restrict results to rocks owned by this ClickUp user_id "
                    "(see clickup_list_members). Alternative to owner_email; if both are "
                    "given, a rock must match either one."
                )
            ),
        ] = None,
    ) -> str:
        """List EOS Rocks (quarterly goals), org-wide by default, one call.

        Rocks are ClickUp tasks in a list named "Rocks", discovered dynamically.
        Pass owner_email or owner_user_id to scope to one person.

        Returns JSON: { rocks: [...], truncated: bool }. Each rock carries id,
        title, measurable, quarter, owner_*, progress_percent, status (with
        ClickUp's raw label in status_raw), rock_type, department, due_date,
        url and weekly_status.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN

        target_quarter = quarter or _current_iso_quarter()
        target_label = _iso_quarter_to_field_label(target_quarter)
        if target_label is None:
            return error_envelope(
                "invalid_argument", f"could not parse 'quarter' as YYYY-Qn: {quarter}", False
            )

        owner_email_norm = owner_email.strip().lower() if owner_email else None
        owner_user_id_norm = str(owner_user_id).strip() if owner_user_id else None

        rocks_lists = await _find_rocks_lists(client)
        if not rocks_lists:
            return dump_json_capped(
                {
                    "rocks": [],
                    "truncated": False,
                    "note": "No list named 'Rocks' found in any workspace visible to this token",
                }
            )

        all_rocks: list[dict] = []
        truncated = False

        for lst in rocks_lists:
            list_id = lst.get("id")
            if not list_id:
                continue
            page = 0
            while page < _MAX_PAGES_PER_LIST:
                params = {"page": page, "include_closed": include_completed}
                try:
                    result = await client.get(f"/list/{list_id}/task", params)
                except ClickUpError as e:
                    return e.to_envelope()
                page_tasks = (result or {}).get("tasks", []) or []
                if not page_tasks:
                    break
                for t in page_tasks:
                    rock = _project_rock(t)
                    if rock["quarter"] != target_quarter:
                        continue
                    if owner_email_norm or owner_user_id_norm:
                        email_match = (
                            owner_email_norm is not None
                            and (rock["owner_email"] or "").strip().lower() == owner_email_norm
                        )
                        id_match = (
                            owner_user_id_norm is not None
                            and rock["owner_user_id"] == owner_user_id_norm
                        )
                        if not (email_match or id_match):
                            continue
                    all_rocks.append(rock)
                if len(page_tasks) < CLICKUP_PAGE_SIZE:
                    break
                page += 1
            else:
                truncated = True

        return dump_json_capped({"rocks": all_rocks, "truncated": truncated})
