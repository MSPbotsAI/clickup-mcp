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
        """Get a ClickUp space's settings and status workflow.

        Returns the raw space object: id, name, private, statuses[] (the
        space's custom status workflow, inherited by folders/lists unless
        they override it), multiple_assignees, and features {} (which
        ClickUp features — time tracking, tags, due dates, etc. — are on).
        """
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
        """List every folder in a ClickUp space.

        Returns JSON with a `folders` array; each entry has id/name/
        task_count and a nested lists[] summary (id/name/task_count).
        archived=True includes archived folders too (excluded by default).
        """
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
        """List folderless lists in a ClickUp space (lists not inside any folder).

        Returns JSON with a `lists` array; each entry has id/name/content/
        status/task_count. Lists that live inside a folder are not
        included here — use clickup_get_folder_lists for those.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/space/{space_id}/list", {"archived": archived})
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
