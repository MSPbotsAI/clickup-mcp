import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import ClickUpClient, ClickUpError

_NO_TOKEN = "Error: No ClickUp token configured. Set CLICKUP_API_TOKEN or use AUTH_MODE=gateway."


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_attach_task_file(
        task_id: str,
        file_content_base64: str,
        filename: str,
        custom_task_ids: bool = False,
        team_id: str | None = None,
    ) -> str:
        """Upload a file (e.g. an image) as an attachment on a ClickUp task.

        API: POST /task/{task_id}/attachment

        Note: this uploads the file's raw bytes directly — ClickUp's API does
        not accept a remote URL for this endpoint.

        Args:
            task_id: The task ID, or the custom ID when custom_task_ids is True.
            file_content_base64: Required. The file's raw bytes, base64-encoded.
            filename: Required. The file name to send with the upload (e.g.
                "screenshot.png").
            custom_task_ids: Set True to look up the task by its custom ID
                (e.g. "ABC-123"). Requires team_id.
            team_id: The workspace/team ID. Required when custom_task_ids is True.
        """
        client = client_factory()
        if client is None:
            return _NO_TOKEN
        if custom_task_ids and not team_id:
            return "Error: team_id is required when custom_task_ids is True."
        params: dict = {}
        if custom_task_ids:
            params["custom_task_ids"] = "true"
            params["team_id"] = team_id
        try:
            result = await client.post_multipart(
                f"/task/{task_id}/attachment",
                field_name="attachment",
                file_content_base64=file_content_base64,
                filename=filename,
                params=params,
            )
            return json.dumps(result, indent=2)
        except ClickUpError as e:
            return f"Error: {e}"
