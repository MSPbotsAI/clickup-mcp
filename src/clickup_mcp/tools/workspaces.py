import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_workspaces() -> str:
        """Get all ClickUp workspaces (teams) accessible with the current token."""
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get("/team")
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_list_spaces(team_id: str, archived: bool = False) -> str:
        """List all spaces in a ClickUp workspace.

        Args:
            team_id: The workspace/team ID.
            archived: Include archived spaces (default: False).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get(f"/team/{team_id}/space", {"archived": archived})
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
