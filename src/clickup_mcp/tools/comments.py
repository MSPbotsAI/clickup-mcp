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
    async def clickup_get_task_comments(
        task_id: Annotated[str, Field(description="The task ID.")],
        start_id: Annotated[
            str | None, Field(description="Comment ID to start from (for pagination).")
        ] = None,
    ) -> str:
        """Get all comments on a ClickUp task."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params: dict = {}
        if start_id is not None:
            params["start_id"] = start_id
        try:
            result = await client.get(f"/task/{task_id}/comment", params or None)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool()
    async def clickup_create_task_comment(
        task_id: Annotated[str, Field(description="The task ID to comment on.")],
        comment_text: Annotated[str, Field(description="The comment text (markdown supported).")],
        notify_all: Annotated[bool, Field(description="Notify all task assignees.")] = False,
        assignee: Annotated[
            int | None, Field(description="User ID to assign the task to when posting this comment.")
        ] = None,
    ) -> str:
        """Create a comment on a ClickUp task."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {
            "comment_text": comment_text,
            "notify_all": notify_all,
        }
        if assignee is not None:
            body["assignee"] = assignee
        try:
            result = await client.post(f"/task/{task_id}/comment", body)
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()
