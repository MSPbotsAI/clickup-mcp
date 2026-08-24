from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_list(
        list_id: Annotated[str, Field(description="The list ID.")],
    ) -> str:
        """Get a ClickUp list's metadata, defaults, and status workflow.

        Returns the raw list object: id, name, content, status (current
        list status), priority, assignee, due_date, folder {id, name},
        space {id, name}, task_count, and the statuses[] array tasks in
        this list can use.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/list/{list_id}")
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool()
    async def clickup_create_list_in_folder(
        folder_id: Annotated[str, Field(description="The folder ID where the list will be created.")],
        name: Annotated[str, Field(description="Name for the new list.")],
        content: Annotated[str | None, Field(description="Description/content for the list.")] = None,
        due_date: Annotated[
            int | None, Field(description="Due date as Unix timestamp in milliseconds.")
        ] = None,
        priority: Annotated[
            int | None, Field(description="Priority level (1=urgent, 2=high, 3=normal, 4=low).")
        ] = None,
        assignee: Annotated[int | None, Field(description="User ID to assign as default assignee.")] = None,
        status: Annotated[str | None, Field(description="Default status for tasks in this list.")] = None,
    ) -> str:
        """Create a new list inside a ClickUp folder.

        Returns the created list object (id, name, content, folder, space,
        task_count=0, statuses[]). status/priority/assignee/due_date only
        set defaults applied to tasks created in this list afterward.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
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
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool()
    async def clickup_create_folderless_list(
        space_id: Annotated[str, Field(description="The space ID where the list will be created.")],
        name: Annotated[str, Field(description="Name for the new list.")],
        content: Annotated[str | None, Field(description="Description/content for the list.")] = None,
        due_date: Annotated[
            int | None, Field(description="Due date as Unix timestamp in milliseconds.")
        ] = None,
        priority: Annotated[
            int | None, Field(description="Priority level (1=urgent, 2=high, 3=normal, 4=low).")
        ] = None,
        assignee: Annotated[int | None, Field(description="User ID to assign as default assignee.")] = None,
        status: Annotated[str | None, Field(description="Default status for tasks in this list.")] = None,
    ) -> str:
        """Create a new list directly in a ClickUp space, with no parent folder.

        Returns the created list object (id, name, content, space,
        task_count=0, statuses[]). Same optional defaults as
        clickup_create_list_in_folder: they only apply to tasks created
        in this list afterward.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
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
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_update_list(
        list_id: Annotated[str, Field(description="The list ID to update.")],
        name: Annotated[str | None, Field(description="New name for the list.")] = None,
        content: Annotated[str | None, Field(description="New description/content.")] = None,
        due_date: Annotated[
            int | None, Field(description="New due date as Unix timestamp in milliseconds.")
        ] = None,
        priority: Annotated[
            int | None, Field(description="Priority level (1=urgent, 2=high, 3=normal, 4=low).")
        ] = None,
        assignee: Annotated[
            str | None, Field(description="'none' to unassign, or user ID to set assignee.")
        ] = None,
        unset_status: Annotated[
            bool | None,
            Field(
                description=(
                    "Set True to clear the list's default status. This does not "
                    "change the status of tasks already in the list."
                )
            ),
        ] = None,
    ) -> str:
        """Update a ClickUp list's name, content, defaults, or default status.

        Returns the updated list object. This is a partial update — only
        fields you pass are changed. unset_status/priority/due_date/assignee
        only affect the list's own defaults for future tasks; they do not
        retroactively change any task already in the list.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
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
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
