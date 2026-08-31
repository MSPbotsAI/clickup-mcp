import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

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
from ._teams import (
    ambiguous_write_envelope,
    annotate,
    invalidate,
    is_team_not_authorized,
    is_workspace_miss,
    resolve_team_scope,
    team_error_envelope,
)


class CustomFieldValue(BaseModel):
    id: str = Field(description="ID of the custom field.")
    value: str = Field(
        description=(
            "Value for the custom field, always passed as a string — the "
            "format depends on the field type: text/url/email/phone/"
            "dropdown (option UUID): the value directly. number/money/"
            'rating: the number as a string (e.g. "42"). checkbox/button: '
            '"true" or "false". labels: JSON array of UUIDs (e.g. '
            '\'["uuid1","uuid2"]\'). relationships/people/files (e.g. the '
            "\"0.1 Requester\" users field): JSON with add/rem arrays "
            '(e.g. \'{"add":["id1"],"rem":["id2"]}\'). progress: JSON with '
            'a current value (e.g. \'{"current":50}\'). date: NOT '
            "auto-converted from a YYYY-MM-DD string — pass the epoch-"
            'milliseconds timestamp as a numeric string (e.g. "1735689600000").'
        )
    )


def _coerce_custom_field_value(value: str) -> Any:
    """Turn a custom_fields value string into the JSON shape ClickUp's API
    expects. Values that parse as JSON (numbers, booleans, arrays, objects —
    covering number/money/rating/checkbox/labels/relationships/people/
    files/progress) are sent as that parsed value; anything else (plain
    text, URLs, emails, dropdown option UUIDs) is sent as the literal
    string. Does NOT special-case date strings — see CustomFieldValue's
    description.
    """
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


async def _set_custom_fields(
    client: ClickUpClient,
    task_id: str,
    custom_fields: list[CustomFieldValue],
    params: dict | None,
) -> list[dict]:
    """Set each custom field value via ClickUp's dedicated per-field
    endpoint (POST /task/{task_id}/field/{field_id}) — the Update/Create
    Task endpoints' own `custom_fields` support differs (Create accepts it
    inline; Update does not, hence this loop), so this helper is shared by
    both tools that need to write field values after task creation.

    Continues past a per-field failure rather than aborting the whole
    call, so one bad field id doesn't block the others from being set.
    """
    results = []
    for cf in custom_fields:
        try:
            await client.post(
                f"/task/{task_id}/field/{cf.id}",
                {"value": _coerce_custom_field_value(cf.value)},
                params,
            )
            results.append({"id": cf.id, "status": "set"})
        except ClickUpError as e:
            results.append({"id": cf.id, "status": "error", "error": e.message})
    return results


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_task(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        custom_task_ids: Annotated[
            bool,
            Field(description='Set True to look up the task by its custom ID (e.g. "ABC-123").'),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID. Optional — resolved from the API token. Only "
                    "pass it if the user named a specific workspace."
                )
            ),
        ] = None,
        include_subtasks: Annotated[
            bool | None, Field(description="Include subtasks in the response.")
        ] = None,
        include_markdown_description: Annotated[
            bool | None, Field(description="Return the task description in Markdown.")
        ] = None,
    ) -> str:
        """Get a single ClickUp task by ID (or by custom ID with custom_task_ids=True).

        Returns the raw task object: id, name, description, status
        {status, type}, priority, assignees[], due_date/start_date (Unix
        ms), list/folder/space, url, and subtasks[] when
        include_subtasks=True. description comes back in ClickUp's own
        format unless include_markdown_description=True.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {}
        if include_subtasks is not None:
            params["include_subtasks"] = include_subtasks
        if include_markdown_description is not None:
            params["include_markdown_description"] = include_markdown_description

        if not custom_task_ids:
            # A native ClickUp task ID is globally unique — no workspace context needed.
            try:
                return dump_json_capped(await client.get(f"/task/{task_id}", params))
            except ClickUpError as e:
                return e.to_envelope()

        # A custom ID is only unique within its own workspace, so ClickUp does
        # need team_id here. Resolve it instead of asking the caller to guess:
        # try each workspace the token can see and stop at the first hit.
        scope = await resolve_team_scope(client, team_id)
        if scope.error:
            return scope.error
        params["custom_task_ids"] = "true"
        for candidate in scope.team_ids:
            try:
                result = await client.get(f"/task/{task_id}", {**params, "team_id": candidate})
            except ClickUpError as e:
                if is_workspace_miss(e):
                    continue
                if is_team_not_authorized(e):
                    invalidate(client)  # the cached workspace list was stale
                    continue
                return e.to_envelope()
            if isinstance(result, dict):
                result["team_id"] = candidate
            return dump_json_capped(annotate(result, scope))
        return error_envelope(
            "not_found",
            f"no task with custom ID '{task_id}' in any workspace this token can access",
            False,
            authorized_workspaces=scope.teams,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_search_tasks(
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID to search in. Optional — resolved from the API "
                    "token, and every accessible workspace is searched when omitted."
                )
            ),
        ] = None,
        page: Annotated[
            int,
            Field(
                description=(
                    "Page number for pagination, 0-indexed (0 = first page). Applies "
                    "only when the search targets a single workspace; paging is "
                    "handled internally otherwise."
                )
            ),
        ] = 0,
        limit: Annotated[int, Field(description="Max tasks to return (1-200).")] = 50,
        order_by: Annotated[
            str | None,
            Field(description="Field to sort by (id, created, updated, due_date); pair with reverse."),
        ] = None,
        reverse: Annotated[
            bool | None, Field(description="Reverse the order_by sort direction (descending).")
        ] = None,
        subtasks: Annotated[
            bool | None, Field(description="Include subtasks among the top-level results.")
        ] = None,
        space_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Filter to these space IDs (OR'd together; ANDed with other "
                    "filters). If you only have a space name, resolve it first via "
                    "clickup_list_spaces."
                )
            ),
        ] = None,
        project_ids: Annotated[
            list[str] | None,
            Field(description="Filter to these folder IDs (ClickUp calls folders 'projects' here)."),
        ] = None,
        list_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Filter to these list IDs. If you only have a list name, "
                    "resolve it first via clickup_get_space_lists or "
                    "clickup_get_folder_lists."
                )
            ),
        ] = None,
        statuses: Annotated[
            list[str] | None, Field(description="Filter to these status names (e.g. 'in progress').")
        ] = None,
        include_closed: Annotated[
            bool | None, Field(description="Include tasks in a closed/done status.")
        ] = None,
        assignees: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Filter to tasks assigned to these ClickUp numeric user IDs — "
                    "not names or emails. Resolve via clickup_list_members first."
                )
            ),
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Filter to tasks carrying these tag names.")] = None,
        due_date_gt: Annotated[
            int | None, Field(description="Due date greater than (Unix ms timestamp).")
        ] = None,
        due_date_lt: Annotated[
            int | None, Field(description="Due date less than (Unix ms timestamp).")
        ] = None,
        date_created_gt: Annotated[
            int | None, Field(description="Creation date greater than (Unix ms timestamp).")
        ] = None,
        date_created_lt: Annotated[
            int | None, Field(description="Creation date less than (Unix ms timestamp).")
        ] = None,
        date_updated_gt: Annotated[
            int | None, Field(description="Update date greater than (Unix ms timestamp).")
        ] = None,
        date_updated_lt: Annotated[
            int | None, Field(description="Update date less than (Unix ms timestamp).")
        ] = None,
    ) -> str:
        """Search tasks across ClickUp workspaces with filters.

        Omit team_id to search every accessible workspace. Prefer
        clickup_list_tasks_for_person for a plain person lookup; use this
        for space/list/tag/date-range filters it lacks.

        Returns { tasks: [...], truncated: bool } plus team_id or
        searched_workspaces. Each task: id/name/status/priority/due_date/
        list_name/space_name/team_id.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {}
        if order_by is not None:
            params["order_by"] = order_by
        if reverse is not None:
            params["reverse"] = reverse
        if subtasks is not None:
            params["subtasks"] = subtasks
        if space_ids is not None:
            params["space_ids[]"] = space_ids
        if project_ids is not None:
            params["project_ids[]"] = project_ids
        if list_ids is not None:
            params["list_ids[]"] = list_ids
        if statuses is not None:
            params["statuses[]"] = statuses
        if include_closed is not None:
            params["include_closed"] = include_closed
        if assignees is not None:
            params["assignees[]"] = assignees
        if tags is not None:
            params["tags[]"] = tags
        if due_date_gt is not None:
            params["due_date_gt"] = due_date_gt
        if due_date_lt is not None:
            params["due_date_lt"] = due_date_lt
        if date_created_gt is not None:
            params["date_created_gt"] = date_created_gt
        if date_created_lt is not None:
            params["date_created_lt"] = date_created_lt
        if date_updated_gt is not None:
            params["date_updated_gt"] = date_updated_gt
        if date_updated_lt is not None:
            params["date_updated_lt"] = date_updated_lt
        scope = await resolve_team_scope(client, team_id)
        if scope.error:
            return scope.error

        limit = max(1, min(limit, MAX_TASKS))

        if len(scope.team_ids) == 1:
            target = scope.team_ids[0]
            try:
                result = await client.get(f"/team/{target}/task", {**params, "page": page})
            except ClickUpError as e:
                return team_error_envelope(e, scope.teams, target)
            space_names = await fetch_space_names(client, target)
            found = (result or {}).get("tasks", []) or []
            payload = {
                "tasks": [project_task(t, target, space_names) for t in found[:limit]],
                "truncated": len(found) > limit,
                "last_page": (result or {}).get("last_page"),
                "team_id": target,
            }
            return dump_json_capped(annotate(payload, scope))

        # Several workspaces and no explicit choice: search all of them and merge,
        # rather than making the caller pick one blind. A single `page` number has
        # no meaning across workspaces, so paging is handled internally here.
        merged: list[dict] = []
        truncated = False
        for target in scope.team_ids:
            if len(merged) >= limit:
                truncated = True
                break
            space_names = await fetch_space_names(client, target)
            current = 0
            while current < MAX_PAGES_PER_WORKSPACE:
                try:
                    result = await client.get(f"/team/{target}/task", {**params, "page": current})
                except ClickUpError as e:
                    return team_error_envelope(e, scope.teams, target)
                page_tasks = (result or {}).get("tasks", []) or []
                if not page_tasks:
                    break
                for task in page_tasks:
                    if len(merged) >= limit:
                        truncated = True
                        break
                    merged.append(project_task(task, target, space_names))
                if truncated or len(page_tasks) < CLICKUP_PAGE_SIZE:
                    break
                current += 1
            else:
                truncated = True
        return dump_json_capped(
            {"tasks": merged, "searched_workspaces": scope.teams, "truncated": truncated}
        )

    @mcp.tool()
    async def clickup_create_task(
        list_id: Annotated[str, Field(description="The list ID where the task will be created.")],
        name: Annotated[str, Field(description="Task name/title.")],
        description: Annotated[
            str | None, Field(description="Task description (markdown supported).")
        ] = None,
        assignees: Annotated[list[int] | None, Field(description="List of user IDs to assign.")] = None,
        tags: Annotated[list[str] | None, Field(description="List of tag names.")] = None,
        status: Annotated[
            str | None, Field(description="Task status (must match a status in the list).")
        ] = None,
        priority: Annotated[
            int | None, Field(description="Priority (1=urgent, 2=high, 3=normal, 4=low).")
        ] = None,
        due_date: Annotated[
            int | None, Field(description="Due date as Unix timestamp in milliseconds.")
        ] = None,
        due_date_time: Annotated[
            bool | None, Field(description="True if due date includes time component.")
        ] = None,
        start_date: Annotated[
            int | None, Field(description="Start date as Unix timestamp in milliseconds.")
        ] = None,
        start_date_time: Annotated[
            bool | None, Field(description="True if start date includes time component.")
        ] = None,
        notify_all: Annotated[
            bool | None,
            Field(description="Notify all assignees of the new task; omit to use ClickUp's own default."),
        ] = None,
        parent: Annotated[
            str | None,
            Field(
                description=(
                    "Parent task ID (to create a subtask) — must be ClickUp's raw "
                    "task ID, not a custom ID like 'DEV-1234' (this tool has no "
                    "custom_task_ids toggle). For a 'subtask of <custom-id>' "
                    "request, first call clickup_get_task(task_id=<custom-id>, "
                    "custom_task_ids=True) to get its raw id and list_id "
                    "(subtasks are created in the parent's own list_id)."
                )
            )
        ] = None,
        time_estimate: Annotated[
            int | None, Field(description="Time estimate in milliseconds.")
        ] = None,
        custom_fields: Annotated[
            list[CustomFieldValue] | None,
            Field(
                description=(
                    "Custom field values to set at creation time, e.g. the "
                    '"0.1 Requester" field: [{"id": '
                    '"024ba696-b139-459b-838f-525c73c5e965", "value": '
                    '\'{"add":["<user id>"]}\'}]. See CustomFieldValue for '
                    "the value-encoding rules per field type."
                )
            ),
        ] = None,
    ) -> str:
        """Create a new task in a ClickUp list.

        Returns the created task object (id, name, url, status,
        assignees[], list/folder/space, due_date/start_date). Setting
        `parent` creates this as a subtask of that task instead of a
        top-level task in the list.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        if assignees is not None:
            body["assignees"] = assignees
        if tags is not None:
            body["tags"] = tags
        if status is not None:
            body["status"] = status
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = due_date
        if due_date_time is not None:
            body["due_date_time"] = due_date_time
        if start_date is not None:
            body["start_date"] = start_date
        if start_date_time is not None:
            body["start_date_time"] = start_date_time
        if notify_all is not None:
            body["notify_all"] = notify_all
        if parent is not None:
            body["parent"] = parent
        if time_estimate is not None:
            body["time_estimate"] = time_estimate
        if custom_fields is not None:
            # Unlike Update Task, Create Task's own endpoint accepts
            # custom_fields inline — no separate per-field call needed here.
            body["custom_fields"] = [
                {"id": cf.id, "value": _coerce_custom_field_value(cf.value)}
                for cf in custom_fields
            ]
        try:
            result = await client.post(f"/list/{list_id}/task", body)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_update_task(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        custom_task_ids: Annotated[
            bool,
            Field(description='Set True to look up the task by its custom ID (e.g. "ABC-123").'),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID. Optional — resolved from the API token when that "
                    "token reaches exactly one workspace. Required if custom_task_ids is "
                    "True and the token can see more than one workspace."
                )
            ),
        ] = None,
        name: Annotated[str | None, Field(description="New task name.")] = None,
        description: Annotated[
            str | None, Field(description="New description (markdown supported).")
        ] = None,
        status: Annotated[
            str | None, Field(description="New status (must match a status in the list).")
        ] = None,
        priority: Annotated[
            int | None,
            Field(description="New priority (1=urgent, 2=high, 3=normal, 4=low, null=none)."),
        ] = None,
        due_date: Annotated[
            int | None, Field(description="New due date as Unix timestamp in milliseconds.")
        ] = None,
        due_date_time: Annotated[
            bool | None, Field(description="True if due date includes time component.")
        ] = None,
        start_date: Annotated[
            int | None, Field(description="New start date as Unix timestamp in milliseconds.")
        ] = None,
        start_date_time: Annotated[
            bool | None, Field(description="True if start date includes time component.")
        ] = None,
        assignees_add: Annotated[
            list[int] | None, Field(description="List of user IDs to add as assignees.")
        ] = None,
        assignees_rem: Annotated[
            list[int] | None, Field(description="List of user IDs to remove from assignees.")
        ] = None,
        archived: Annotated[
            bool | None, Field(description="Archive (True) or unarchive (False) the task.")
        ] = None,
        time_estimate: Annotated[
            int | None, Field(description="New time estimate in milliseconds.")
        ] = None,
        custom_fields: Annotated[
            list[CustomFieldValue] | None,
            Field(
                description=(
                    "Custom field values to set, e.g. the \"0.1 Requester\" "
                    'field: [{"id": "024ba696-b139-459b-838f-525c73c5e965", '
                    '"value": \'{"add":["<user id>"]}\'}]. Each field is set '
                    "via its own upstream call, separate from the other "
                    "fields in this same call — one bad field id does not "
                    "block the others; check the response's "
                    "custom_fields[].status. See CustomFieldValue for the "
                    "value-encoding rules per field type."
                )
            ),
        ] = None,
    ) -> str:
        """Update fields on an existing ClickUp task (partial update).

        Only the fields you pass are changed. Returns the updated task
        object, plus a custom_fields[] array (one {id, status} entry per
        field) when custom_fields was given. assignees_add/assignees_rem
        add or remove individual assignees without resending the full
        list. No notify_all param — ClickUp uses its own default.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if status is not None:
            body["status"] = status
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = due_date
        if due_date_time is not None:
            body["due_date_time"] = due_date_time
        if start_date is not None:
            body["start_date"] = start_date
        if start_date_time is not None:
            body["start_date_time"] = start_date_time
        if assignees_add is not None or assignees_rem is not None:
            body["assignees"] = {
                "add": assignees_add or [],
                "rem": assignees_rem or [],
            }
        if archived is not None:
            body["archived"] = archived
        if time_estimate is not None:
            body["time_estimate"] = time_estimate
        params: dict = {}
        scope = None
        if custom_task_ids:
            # A custom ID is only unique within its workspace. This is a write, so
            # resolve it but never probe several workspaces looking for a match —
            # guessing wrong here would update the wrong task.
            scope = await resolve_team_scope(client, team_id)
            if scope.error:
                return scope.error
            if len(scope.team_ids) != 1:
                return ambiguous_write_envelope(scope.teams)
            params["custom_task_ids"] = "true"
            params["team_id"] = scope.team_ids[0]
        try:
            result = await client.put(f"/task/{task_id}", body, params or None)
        except ClickUpError as e:
            return e.to_envelope()
        result = annotate(result, scope) if scope else result
        if custom_fields is not None:
            # Update Task's own endpoint has no custom_fields support —
            # each field is set via ClickUp's separate per-field endpoint,
            # continuing past individual failures (see _set_custom_fields).
            field_results = await _set_custom_fields(client, task_id, custom_fields, params or None)
            result = {**(result or {}), "custom_fields": field_results}
        return dump_json_capped(result)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def clickup_delete_task(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        confirm: Annotated[
            bool, Field(description="Required — must be set to true to proceed.")
        ] = False,
        custom_task_ids: Annotated[
            bool,
            Field(description='Set True to look up the task by its custom ID (e.g. "ABC-123").'),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID. Optional — resolved from the API token when that "
                    "token reaches exactly one workspace. Required if custom_task_ids is "
                    "True and the token can see more than one workspace."
                )
            ),
        ] = None,
    ) -> str:
        """Delete a ClickUp task.

        Destructive. Requires confirm=true.
        """
        if not confirm:
            return error_envelope(
                "invalid_argument", "destructive operation requires confirm=true", False
            )
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {}
        scope = None
        if custom_task_ids:
            # Same write-safety rule as update/move: resolve the workspace, but
            # never guess across several — a wrong guess here deletes the wrong task.
            scope = await resolve_team_scope(client, team_id)
            if scope.error:
                return scope.error
            if len(scope.team_ids) != 1:
                return ambiguous_write_envelope(scope.teams)
            params["custom_task_ids"] = "true"
            params["team_id"] = scope.team_ids[0]
        try:
            await client.delete(f"/task/{task_id}", params or None)
            payload = {"deleted": True, "task_id": task_id}
            return dump_json_capped(annotate(payload, scope) if scope else payload)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_move_task(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        list_id: Annotated[str, Field(description="The destination list ID.")],
        custom_task_ids: Annotated[
            bool,
            Field(description='Set True to look up the task by its custom ID (e.g. "ABC-123").'),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace/team ID. Optional — resolved from the API token when that "
                    "token reaches exactly one workspace. Required if custom_task_ids is "
                    "True and the token can see more than one workspace."
                )
            ),
        ] = None,
    ) -> str:
        """Move a ClickUp task into a different list.

        Returns the updated task object with its new list/folder/space.
        The task keeps its name, assignees, and comment history; if the
        destination list has no status matching the task's current one,
        ClickUp resets the task's status to the destination list's default.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {}
        scope = None
        if custom_task_ids:
            # Same write-safety rule as update/delete: resolve the workspace, but
            # never guess across several — a wrong guess here moves the wrong task.
            scope = await resolve_team_scope(client, team_id)
            if scope.error:
                return scope.error
            if len(scope.team_ids) != 1:
                return ambiguous_write_envelope(scope.teams)
            params["custom_task_ids"] = "true"
            params["team_id"] = scope.team_ids[0]
        try:
            result = await client.put(f"/task/{task_id}", {"list": {"id": list_id}}, params or None)
            return dump_json_capped(annotate(result, scope) if scope else result)
        except ClickUpError as e:
            return e.to_envelope()
