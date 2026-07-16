import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_list(list_id: str) -> str:
        """Get details of a ClickUp list.

        Args:
            list_id: The list ID.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/list/{list_id}")
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_create_list_in_folder(
        folder_id: str,
        name: str,
        content: str | None = None,
        due_date: int | None = None,
        priority: int | None = None,
        assignee: int | None = None,
        status: str | None = None,
    ) -> str:
        """Create a new list inside a ClickUp folder.

        Args:
            folder_id: The folder ID where the list will be created.
            name: Name for the new list.
            content: Description/content for the list.
            due_date: Due date as Unix timestamp in milliseconds.
            priority: Priority level (1=urgent, 2=high, 3=normal, 4=low).
            assignee: User ID to assign as default assignee.
            status: Default status for tasks in this list.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        body: dict = {"name": name}
        if content is not None:
            body["content"] = content
        if due_date is not None:
            body["due_date"] = due_date
        if priority is not None:
            body["priority"] = priority
        if assignee is not None:
            body["assignee"] = assignee
        if status is not None:
            body["status"] = status
        try:
            result = await client.post(f"/folder/{folder_id}/list", body)
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_create_folderless_list(
        space_id: str,
        name: str,
        content: str | None = None,
        due_date: int | None = None,
        priority: int | None = None,
        assignee: int | None = None,
        status: str | None = None,
    ) -> str:
        """Create a new folderless list directly in a ClickUp space.

        Args:
            space_id: The space ID where the list will be created.
            name: Name for the new list.
            content: Description/content for the list.
            due_date: Due date as Unix timestamp in milliseconds.
            priority: Priority level (1=urgent, 2=high, 3=normal, 4=low).
            assignee: User ID to assign as default assignee.
            status: Default status for tasks in this list.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        body: dict = {"name": name}
        if content is not None:
            body["content"] = content
        if due_date is not None:
            body["due_date"] = due_date
        if priority is not None:
            body["priority"] = priority
        if assignee is not None:
            body["assignee"] = assignee
        if status is not None:
            body["status"] = status
        try:
            result = await client.post(f"/space/{space_id}/list", body)
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_update_list(
        list_id: str,
        name: str | None = None,
        content: str | None = None,
        due_date: int | None = None,
        priority: int | None = None,
        assignee: str | None = None,
        unset_status: bool | None = None,
    ) -> str:
        """Update a ClickUp list.

        Args:
            list_id: The list ID to update.
            name: New name for the list.
            content: New description/content.
            due_date: New due date as Unix timestamp in milliseconds.
            priority: Priority level (1=urgent, 2=high, 3=normal, 4=low).
            assignee: 'none' to unassign, or user ID to set assignee.
            unset_status: Set True to unset the default status.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        body: dict = {}
        if name is not None:
            body["name"] = name
        if content is not None:
            body["content"] = content
        if due_date is not None:
            body["due_date"] = due_date
        if priority is not None:
            body["priority"] = priority
        if assignee is not None:
            body["assignee"] = assignee
        if unset_status is not None:
            body["unset_status"] = unset_status
        try:
            result = await client.put(f"/list/{list_id}", body)
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
