import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_space(space_id: str) -> str:
        """Get details of a ClickUp space.

        Args:
            space_id: The space ID.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}")
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_get_space_folders(space_id: str, archived: bool = False) -> str:
        """List all folders in a ClickUp space.

        Args:
            space_id: The space ID.
            archived: Include archived folders (default: False).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}/folder", {"archived": archived})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_get_space_lists(space_id: str, archived: bool = False) -> str:
        """List all folderless lists in a ClickUp space.

        Args:
            space_id: The space ID.
            archived: Include archived lists (default: False).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}/list", {"archived": archived})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
