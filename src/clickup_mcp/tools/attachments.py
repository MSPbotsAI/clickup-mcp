from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool()
    async def clickup_attach_task_file(
        task_id: Annotated[
            str, Field(description="The task ID, or the custom ID when custom_task_ids is True.")
        ],
        file_content_base64: Annotated[
            str, Field(description="Required. The file's raw bytes, base64-encoded.")
        ],
        filename: Annotated[
            str,
            Field(description='Required. The file name to send with the upload (e.g. "screenshot.png").'),
        ],
        custom_task_ids: Annotated[
            bool,
            Field(
                description=(
                    'Set True to look up the task by its custom ID (e.g. "ABC-123"). '
                    "Requires team_id."
                )
            ),
        ] = False,
        team_id: Annotated[
            str | None,
            Field(description="The workspace/team ID. Required when custom_task_ids is True."),
        ] = None,
    ) -> str:
        """Upload a file (e.g. an image) as an attachment on a ClickUp task.

        Note: this uploads the file's raw bytes directly — ClickUp's API does
        not accept a remote URL for this endpoint.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if custom_task_ids and not team_id:
            return error_envelope(
                "invalid_argument", "team_id is required when custom_task_ids is True", False
            )
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
            return dump_json_capped(result)
        except ClickUpError as e:
            return e.to_envelope()

    @mcp.tool()
    async def clickup_create_comment_with_image(
        task_id: Annotated[str, Field(description="The task ID to attach the file to and comment on.")],
        file_content_base64: Annotated[
            str, Field(description="Required. The file's raw bytes, base64-encoded.")
        ],
        filename: Annotated[str, Field(description='Required. The file name (e.g. "screenshot.png").')],
        comment_text: Annotated[
            str | None, Field(description="Optional. Extra text to show above the image in the comment.")
        ] = None,
        notify_all: Annotated[bool, Field(description="Notify all task assignees.")] = False,
        assignee: Annotated[
            int | None, Field(description="User ID to assign the task to when posting this comment.")
        ] = None,
    ) -> str:
        """Upload an image (or any file) and post it inline inside a new
        task comment, in one call.

        ClickUp's comment API has no attachment field of its own — this tool
        uploads the file to the task first, then creates a comment whose text
        embeds the uploaded file's URL using Markdown image syntax
        (`![filename](url)`), which ClickUp's comment renderer displays as
        an inline image rather than a plain link.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            attachment = await client.post_multipart(
                f"/task/{task_id}/attachment",
                field_name="attachment",
                file_content_base64=file_content_base64,
                filename=filename,
            )
        except ClickUpError as e:
            return e.to_envelope()
        url = attachment.get("url") if isinstance(attachment, dict) else None
        if not url:
            return error_envelope(
                "upstream_error", f"upload succeeded but no url was returned: {attachment}", False
            )
        markdown_image = f"![{filename}]({url})"
        full_text = f"{comment_text}\n\n{markdown_image}" if comment_text else markdown_image
        body: dict = {"comment_text": full_text, "notify_all": notify_all}
        if assignee is not None:
            body["assignee"] = assignee
        try:
            comment_result = await client.post(f"/task/{task_id}/comment", body)
        except ClickUpError as e:
            return error_envelope(
                "upstream_error",
                f"comment creation failed after file was uploaded successfully (url={url}): {e}",
                True,
            )
        return dump_json_capped({"attachment": attachment, "comment": comment_result})
