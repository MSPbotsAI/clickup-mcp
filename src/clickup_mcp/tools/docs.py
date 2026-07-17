import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_doc_page(
        workspace_id: str,
        doc_id: str,
        page_id: str,
        content_format: str = "text/md",
    ) -> str:
        """Get a single page from a ClickUp Doc.

        Args:
            workspace_id: The Workspace (team) ID.
            doc_id: The Doc ID.
            page_id: The Page ID.
            content_format: Page content format: "text/md" (default) or "text/plain".
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        try:
            result = await client.get_v3(
                f"/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}",
                {"content_format": content_format},
            )
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
