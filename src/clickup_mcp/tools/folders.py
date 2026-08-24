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
    async def clickup_get_folder(
        folder_id: Annotated[str, Field(description="The folder ID.")],
    ) -> str:
        """Get a ClickUp folder's metadata and the lists inside it.

        Returns the raw folder object: id, name, orderindex, hidden,
        space {id, name}, task_count (total across all its lists), and a
        lists[] array (each with id/name/task_count). Use
        clickup_get_folder_lists instead if you only need the lists.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/folder/{folder_id}")
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_folder_lists(
        folder_id: Annotated[str, Field(description="The folder ID.")],
        archived: Annotated[bool, Field(description="Include archived lists.")] = False,
    ) -> str:
        """List every list inside a ClickUp folder.

        Returns JSON with a `lists` array; each entry has id/name/content,
        status/priority/assignee defaults, task_count, and its statuses[]
        workflow. archived=True includes archived lists too (excluded by
        default).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/folder/{folder_id}/list", {"archived": archived})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool()
    async def clickup_create_folder(
        space_id: Annotated[str, Field(description="The space ID where the folder will be created.")],
        name: Annotated[str, Field(description="Name for the new folder.")],
    ) -> str:
        """Create a new folder in a ClickUp space.

        Returns the created folder object (id, name, orderindex, space,
        an empty lists[]). Folders have no assignee/watcher of their own,
        so this does not send any ClickUp notification.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.post(f"/space/{space_id}/folder", {"name": name})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def clickup_update_folder(
        folder_id: Annotated[str, Field(description="The folder ID to update.")],
        name: Annotated[str, Field(description="New name for the folder.")],
    ) -> str:
        """Rename a ClickUp folder (the only field this endpoint updates).

        Returns the updated folder object (id, name, orderindex, space,
        lists[]). The lists and tasks inside the folder are unaffected —
        only the folder's own name changes.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(f"/folder/{folder_id}", {"name": name})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def clickup_delete_folder(
        folder_id: Annotated[str, Field(description="The folder ID to delete.")],
        confirm: Annotated[
            bool, Field(description="Required — must be set to true to proceed.")
        ] = False,
    ) -> str:
        """Delete a ClickUp folder.

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
            await client.delete(f"/folder/{folder_id}")
            return dump_json_capped({"deleted": True, "folder_id": folder_id})
        except ClickUpError as e:
            return e.to_envelope()
