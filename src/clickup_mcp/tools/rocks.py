import json
from collections.abc import Callable
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."

# Same pagination convention as clickup_search_tasks / clickup_list_tasks_for_person:
# ClickUp's list-scoped "Get Tasks" endpoint (GET /list/:list_id/task) returns up
# to 100 tasks per page with no total-count/last-page field — stop once a page
# comes back with fewer than 100.
_CLICKUP_PAGE_SIZE = 100
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


async def _find_rocks_lists(client: ClickUpClient) -> list[dict]:
    """Discover every list literally named "Rocks" (case-insensitive) across
    every workspace/space this token can see, folder or folderless."""
    try:
        team_result = await client.get("/team")
    except ClickUpError:
        return []
    teams = (team_result or {}).get("teams", []) or []

    found: list[dict] = []
    for team in teams:
        team_id = team.get("id")
        if not team_id:
            continue
        try:
            space_result = await client.get(f"/team/{team_id}/space", {"archived": False})
        except ClickUpError:
            continue
        for space in (space_result or {}).get("spaces", []) or []:
            space_id = space.get("id")
            if not space_id:
                continue
            try:
                folderless = await client.get(f"/space/{space_id}/list", {"archived": False})
                for lst in (folderless or {}).get("lists", []) or []:
                    if (lst.get("name") or "").strip().lower() == _ROCKS_LIST_NAME:
                        found.append(lst)
            except ClickUpError:
                pass
            try:
                folder_result = await client.get(f"/space/{space_id}/folder", {"archived": False})
            except ClickUpError:
                continue
            for folder in (folder_result or {}).get("folders", []) or []:
                for lst in folder.get("lists", []) or []:
                    if (lst.get("name") or "").strip().lower() == _ROCKS_LIST_NAME:
                        found.append(lst)
    return found


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_list_rocks_for_org(
        quarter: str | None = None,
        include_completed: bool = True,
    ) -> str:
        """List all EOS Rocks (quarterly goals) across the organization in one
        call — no person/owner argument, this is org-wide by design so a
        quarterly review needs one call instead of one per person.

        Rocks in this ClickUp workspace are regular tasks living in a list
        literally named "Rocks" (discovered dynamically by name, not a
        hardcoded ID), with dedicated custom fields: Quarter, Rocks Status,
        Rock Type, Department, and Progress (manual and/or auto). This tool
        reads those fields and normalizes them into a fixed shape — see
        module-level notes on two known gaps: there is no dedicated
        "measurable" field (falls back to the task description, or null if
        that's empty too), and no structured weekly on/off tracking field
        exists anywhere in the source data (always returned as an empty
        list).

        Args:
            quarter: Target quarter as "YYYY-Qn", e.g. "2026-Q3". Defaults to
                the current UTC quarter if omitted.
            include_completed: Include rocks already marked Completed.
                Default True — quarterly reviews usually want to see what
                finished, not just what's outstanding.

        Returns JSON: { rocks: [...], truncated: bool }. Each rock has
        id/title/measurable/quarter/owner_email/owner_user_id/owner_name/
        progress_percent/status/rock_type/department/due_date/url/
        weekly_status. `status` is always one of on_track/off_track/done/
        missed/open (ClickUp's 6 raw status options are mapped down to
        these 5 — see module comment for the exact mapping and its
        rationale). `truncated: true` means a list's task count hit the
        internal page-count safety cap — a defensive fallback, not expected
        in normal use for a curated Rocks list.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN

        target_quarter = quarter or _current_iso_quarter()
        target_label = _iso_quarter_to_field_label(target_quarter)
        if target_label is None:
            return f"Error: could not parse 'quarter' as YYYY-Qn: {quarter}"

        rocks_lists = await _find_rocks_lists(client)
        if not rocks_lists:
            return json.dumps(
                {
                    "rocks": [],
                    "truncated": False,
                    "note": "No list named 'Rocks' found in any workspace visible to this token",
                },
                indent=2,
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
                    return f"Error: {e}"
                page_tasks = (result or {}).get("tasks", []) or []
                if not page_tasks:
                    break
                for t in page_tasks:
                    rock = _project_rock(t)
                    if rock["quarter"] == target_quarter:
                        all_rocks.append(rock)
                if len(page_tasks) < _CLICKUP_PAGE_SIZE:
                    break
                page += 1
            else:
                truncated = True

        return json.dumps({"rocks": all_rocks, "truncated": truncated}, indent=2, ensure_ascii=False)
