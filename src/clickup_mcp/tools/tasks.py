import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_task(
        task_id: str,
        custom_task_ids: bool = False,
        team_id: str | None = None,
        include_subtasks: bool | None = None,
        include_markdown_description: bool | None = None,
    ) -> str:
        """Get a ClickUp task by ID or by custom ID.

        Args:
            task_id: The task ID, or the custom ID when custom_task_ids is True.
            custom_task_ids: Set True to look up the task by its custom ID
                (e.g. "ABC-123"). Requires team_id.
            team_id: The workspace/team ID. Required when custom_task_ids is True.
            include_subtasks: Include subtasks in the response.
            include_markdown_description: Return the task description in Markdown.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        if custom_task_ids and not team_id:
            return "Error: team_id is required when custom_task_ids is True."
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
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_search_tasks(
        team_id: str,
        page: int = 0,
        order_by: str | None = None,
        reverse: bool | None = None,
        subtasks: bool | None = None,
        space_ids: list[str] | None = None,
        project_ids: list[str] | None = None,
        list_ids: list[str] | None = None,
        statuses: list[str] | None = None,
        include_closed: bool | None = None,
        assignees: list[str] | None = None,
        tags: list[str] | None = None,
        due_date_gt: int | None = None,
        due_date_lt: int | None = None,
        date_created_gt: int | None = None,
        date_created_lt: int | None = None,
        date_updated_gt: int | None = None,
        date_updated_lt: int | None = None,
    ) -> str:
        """Search tasks in a ClickUp workspace with filters.

        Args:
            team_id: The workspace/team ID to search in.
            page: Page number for pagination (default: 0).
            order_by: Field to sort by (id, created, updated, due_date).
            reverse: Reverse sort order.
            subtasks: Include subtasks.
            space_ids: Filter by space IDs.
            project_ids: Filter by project/folder IDs.
            list_ids: Filter by list IDs.
            statuses: Filter by status names.
            include_closed: Include closed tasks.
            assignees: Filter by assignee user IDs.
            tags: Filter by tag names.
            due_date_gt: Due date greater than (Unix ms timestamp).
            due_date_lt: Due date less than (Unix ms timestamp).
            date_created_gt: Creation date greater than (Unix ms timestamp).
            date_created_lt: Creation date less than (Unix ms timestamp).
            date_updated_gt: Update date greater than (Unix ms timestamp).
            date_updated_lt: Update date less than (Unix ms timestamp).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
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
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_create_task(
        list_id: str,
        name: str,
        description: str | None = None,
        assignees: list[int] | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        priority: int | None = None,
        due_date: int | None = None,
        due_date_time: bool | None = None,
        start_date: int | None = None,
        start_date_time: bool | None = None,
        notify_all: bool | None = None,
        parent: str | None = None,
        time_estimate: int | None = None,
    ) -> str:
        """Create a new task in a ClickUp list.

        Args:
            list_id: The list ID where the task will be created.
            name: Task name/title.
            description: Task description (markdown supported).
            assignees: List of user IDs to assign.
            tags: List of tag names.
            status: Task status (must match a status in the list).
            priority: Priority (1=urgent, 2=high, 3=normal, 4=low).
            due_date: Due date as Unix timestamp in milliseconds.
            due_date_time: True if due date includes time component.
            start_date: Start date as Unix timestamp in milliseconds.
            start_date_time: True if start date includes time component.
            notify_all: Notify all assignees.
            parent: Parent task ID (to create a subtask).
            time_estimate: Time estimate in milliseconds.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
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
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_update_task(
        task_id: str,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: int | None = None,
        due_date: int | None = None,
        due_date_time: bool | None = None,
        start_date: int | None = None,
        start_date_time: bool | None = None,
        assignees_add: list[int] | None = None,
        assignees_rem: list[int] | None = None,
        archived: bool | None = None,
        time_estimate: int | None = None,
    ) -> str:
        """Update an existing ClickUp task.

        Args:
            task_id: The task ID to update.
            name: New task name.
            description: New description (markdown supported).
            status: New status (must match a status in the list).
            priority: New priority (1=urgent, 2=high, 3=normal, 4=low, null=none).
            due_date: New due date as Unix timestamp in milliseconds.
            due_date_time: True if due date includes time component.
            start_date: New start date as Unix timestamp in milliseconds.
            start_date_time: True if start date includes time component.
            assignees_add: List of user IDs to add as assignees.
            assignees_rem: List of user IDs to remove from assignees.
            archived: Archive (True) or unarchive (False) the task.
            time_estimate: New time estimate in milliseconds.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
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
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_delete_task(task_id: str) -> str:
        """Delete a ClickUp task.

        Args:
            task_id: The task ID to delete.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            await client.delete(f"/task/{task_id}")
            return f"Task {task_id} deleted successfully."
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_move_task(task_id: str, list_id: str) -> str:
        """Move a ClickUp task to a different list.

        Args:
            task_id: The task ID to move.
            list_id: The destination list ID.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.put(f"/task/{task_id}", {"list": {"id": list_id}})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
