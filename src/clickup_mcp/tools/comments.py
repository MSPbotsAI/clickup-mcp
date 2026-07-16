import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_get_task_comments(task_id: str, start_id: str | None = None) -> str:
        """Get all comments on a ClickUp task.

        Args:
            task_id: The task ID.
            start_id: Comment ID to start from (for pagination).
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        params: dict = {}
        if start_id is not None:
            params["start_id"] = start_id
        try:
            result = await client.get(f"/task/{task_id}/comment", params or None)
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clickup_create_task_comment(
        task_id: str,
        comment_text: str,
        notify_all: bool = False,
        assignee: int | None = None,
    ) -> str:
        """Create a comment on a ClickUp task.

        Args:
            task_id: The task ID to comment on.
            comment_text: The comment text (markdown supported).
            notify_all: Notify all task assignees (default: False).
            assignee: User ID to assign the task to when posting this comment.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        body: dict = {
            "comment_text": comment_text,
            "notify_all": notify_all,
        }
        if assignee is not None:
            body["assignee"] = assignee
        try:
            result = await client.post(f"/task/{task_id}/comment", body)
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
