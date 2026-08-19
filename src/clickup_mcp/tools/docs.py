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
    async def clickup_get_doc_page(
        workspace_id: Annotated[str, Field(description="The Workspace (team) ID.")],
        doc_id: Annotated[str, Field(description="The Doc ID.")],
        page_id: Annotated[str, Field(description="The Page ID.")],
        content_format: Annotated[
            str, Field(description='Page content format: "text/md" (default) or "text/plain".')
        ] = "text/md",
    ) -> str:
        """Get a single page from a ClickUp Doc."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get_v3(
                f"/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}",
                {"content_format": content_format},
            )
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
