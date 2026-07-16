import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_folder(folder_id: str) -> str:
        """Get details of a ClickUp folder.

        Args:
            folder_id: The folder ID.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/folder/{folder_id}")
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_get_folder_lists(folder_id: str, archived: bool = False) -> str:
        """List all lists in a ClickUp folder.

        Args:
            folder_id: The folder ID.
            archived: Include archived lists (default: False).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/folder/{folder_id}/list", {"archived": archived})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_create_folder(space_id: str, name: str) -> str:
        """Create a new folder in a ClickUp space.

        Args:
            space_id: The space ID where the folder will be created.
            name: Name for the new folder.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.post(f"/space/{space_id}/folder", {"name": name})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_update_folder(folder_id: str, name: str) -> str:
        """Update a ClickUp folder.

        Args:
            folder_id: The folder ID to update.
            name: New name for the folder.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.put(f"/folder/{folder_id}", {"name": name})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_delete_folder(folder_id: str) -> str:
        """Delete a ClickUp folder.

        Args:
            folder_id: The folder ID to delete.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            await client.delete(f"/folder/{folder_id}")
            return f"Folder {folder_id} deleted successfully."
        except ClickUpError as e:
            return f"Error: {e}"
