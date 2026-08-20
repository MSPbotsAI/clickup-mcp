from datetime import UTC, datetime

from .._json import error_envelope
from ..api_client import ClickUpClient, ClickUpError

NO_TOKEN = error_envelope(
    "not_configured", "No ClickUp API token. Send the X-Clickup-Token header.", False
)

# ClickUp's list endpoints page 100 items at a time and expose no total-count
# or last-page field — the documented convention is to keep incrementing `page`
# until a page returns fewer than 100 items. See https://clickup.com/api docs,
# "Get Filtered Team Tasks".
CLICKUP_PAGE_SIZE = 100

# Safety nets on top of the vendor's paging, so a pathological workspace can
# never turn one tool call into an unbounded crawl.
MAX_PAGES_PER_WORKSPACE = 20
MAX_TASKS = 200


def ms_to_iso(ms_value) -> str | None:
    if not ms_value:
        return None
    try:
        return (
            datetime.fromtimestamp(int(ms_value) / 1000, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError):
        return None


async def fetch_space_names(client: ClickUpClient, team_id: str) -> dict[str, str]:
    """Map space id -> name for one workspace.

    The filtered-team-tasks endpoint carries space.id but not space.name, so
    resolve it once per workspace rather than once per task. A failure here is
    non-fatal: space_name simply stays null.
    """
    try:
        result = await client.get(f"/team/{team_id}/space", {"archived": False})
    except ClickUpError:
        return {}
    return {
        space["id"]: space.get("name")
        for space in (result or {}).get("spaces", []) or []
        if space.get("id")
    }


def project_task(task: dict, team_id: str, space_names: dict[str, str]) -> dict:
    """Reduce a ClickUp task to the fields an agent actually reads.

    ClickUp's native task object carries the workspace's whole custom-field
    schema per task, so a single raw task can exceed the entire response budget
    — which silently truncated result lists down to nothing. Project instead.
    """
    status = task.get("status") or {}
    priority = task.get("priority") or {}
    space = task.get("space") or {}
    list_obj = task.get("list") or {}
    return {
        "id": task.get("id"),
        "custom_id": task.get("custom_id"),
        "name": task.get("name"),
        "status": status.get("status"),
        "status_type": status.get("type"),
        "priority": priority.get("priority") if isinstance(priority, dict) else None,
        "due_date": ms_to_iso(task.get("due_date")),
        "date_closed": ms_to_iso(task.get("date_closed")),
        "url": task.get("url"),
        "list_name": list_obj.get("name"),
        "space_name": space_names.get(space.get("id")),
        "team_id": team_id,
    }
