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
    async def clickup_get_space(
        space_id: Annotated[str, Field(description="The space ID.")],
    ) -> str:
        """Get details of a ClickUp space."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}")
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_space_folders(
        space_id: Annotated[str, Field(description="The space ID.")],
        archived: Annotated[bool, Field(description="Include archived folders.")] = False,
    ) -> str:
        """List all folders in a ClickUp space."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}/folder", {"archived": archived})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_space_lists(
        space_id: Annotated[str, Field(description="The space ID.")],
        archived: Annotated[bool, Field(description="Include archived lists.")] = False,
    ) -> str:
        """List all folderless lists in a ClickUp space."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}/list", {"archived": archived})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
