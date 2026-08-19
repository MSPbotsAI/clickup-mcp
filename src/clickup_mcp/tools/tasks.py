from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_task(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        custom_task_ids: Annotated[
            bool,
            Field(
                description=(
                    'Set True to look up the task by its custom ID (e.g. "ABC-123"). '
                    "Requires team_id."
                )
            ),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(description="The workspace/team ID. Required when custom_task_ids is True."),
        ] = None,
        include_subtasks: Annotated[
            bool | None, Field(description="Include subtasks in the response.")
        ] = None,
        include_markdown_description: Annotated[
            bool | None, Field(description="Return the task description in Markdown.")
        ] = None,
    ) -> str:
        """Get a ClickUp task by ID or by custom ID."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if custom_task_ids and not team_id:
            return error_envelope(
                "invalid_argument", "team_id is required when custom_task_ids is True", False
            )
        params: dict = {}
        if custom_task_ids:
            params["custom_task_ids"] = "true"
            params["team_id"] = team_id
        if include_subtasks is not None:
            params["include_subtasks"] = include_subtasks
        if include_markdown_description is not None:
            params["include_markdown_description"] = include_markdown_description
        try:
            result = await client.get(f"/task/{task_id}", params)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_search_tasks(
        team_id: Annotated[str, Field(description="The workspace/team ID to search in.")],
        page: Annotated[int, Field(description="Page number for pagination.")] = 0,
        order_by: Annotated[
            str | None, Field(description="Field to sort by (id, created, updated, due_date).")
        ] = None,
        reverse: Annotated[bool | None, Field(description="Reverse sort order.")] = None,
        subtasks: Annotated[bool | None, Field(description="Include subtasks.")] = None,
        space_ids: Annotated[list[str] | None, Field(description="Filter by space IDs.")] = None,
        project_ids: Annotated[
            list[str] | None, Field(description="Filter by project/folder IDs.")
        ] = None,
        list_ids: Annotated[list[str] | None, Field(description="Filter by list IDs.")] = None,
        statuses: Annotated[list[str] | None, Field(description="Filter by status names.")] = None,
        include_closed: Annotated[bool | None, Field(description="Include closed tasks.")] = None,
        assignees: Annotated[
            list[str] | None, Field(description="Filter by assignee user IDs.")
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Filter by tag names.")] = None,
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
        """Search tasks in a ClickUp workspace with filters."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {"page": page}
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
        try:
            result = await client.get(f"/team/{team_id}/task", params)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

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
        notify_all: Annotated[bool | None, Field(description="Notify all assignees.")] = None,
        parent: Annotated[
            str | None, Field(description="Parent task ID (to create a subtask).")
        ] = None,
        time_estimate: Annotated[
            int | None, Field(description="Time estimate in milliseconds.")
        ] = None,
    ) -> str:
        """Create a new task in a ClickUp list."""
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
        try:
            result = await client.post(f"/list/{list_id}/task", body)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_update_task(
        task_id: Annotated[str, Field(description="The task ID to update.")],
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
    ) -> str:
        """Update an existing ClickUp task."""
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
        try:
            result = await client.put(f"/task/{task_id}", body)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def clickup_delete_task(
        task_id: Annotated[str, Field(description="The task ID to delete.")],
        confirm: Annotated[
            bool, Field(description="Required — must be set to true to proceed.")
        ] = False,
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
        try:
            await client.delete(f"/task/{task_id}")
            return dump_json_capped({"deleted": True, "task_id": task_id})
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_move_task(
        task_id: Annotated[str, Field(description="The task ID to move.")],
        list_id: Annotated[str, Field(description="The destination list ID.")],
    ) -> str:
        """Move a ClickUp task to a different list."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(f"/task/{task_id}", {"list": {"id": list_id}})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
