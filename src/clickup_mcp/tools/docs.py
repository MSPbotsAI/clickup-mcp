from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ClickUpClient, ClickUpError
from ._common import NO_TOKEN
from ._teams import (
    annotate,
    invalidate,
    is_team_not_authorized,
    is_workspace_miss,
    resolve_team_scope,
)


def register(mcp: FastMCP, client_factory: Callable[[], ClickUpClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def clickup_get_doc_page(
        doc_id: Annotated[str, Field(description="The Doc ID.")],
        page_id: Annotated[str, Field(description="The Page ID.")],
        workspace_id: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace (team) ID. Optional — resolved from the API token. Only "
                    "pass it if the user named a specific workspace."
                )
            ),
        ] = None,
        content_format: Annotated[
            str, Field(description='Page content format: "text/md" (default) or "text/plain".')
        ] = "text/md",
    ) -> str:
        """Get one page's content from a ClickUp Doc. Requires doc_id and
        page_id already known — no name/search-based resolution exists
        here, so ask for the ID or a ClickUp link if the user only names
        the doc (e.g. "the design doc").

        Returns the raw page object: id, name, content (rendered in the
        requested content_format), doc_id, parent_page_id, and
        date_updated. Use content_format="text/plain" to strip Markdown.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        scope = await resolve_team_scope(client, workspace_id)
        if scope.error:
            return scope.error

        # Doc/page IDs are scoped to a workspace, so try each one the token can
        # see and stop at the first hit rather than asking the caller to guess.
        for candidate in scope.team_ids:
            try:
                result = await client.get_v3(
                    f"/workspaces/{candidate}/docs/{doc_id}/pages/{page_id}",
                    {"content_format": content_format},
                )
            except ClickUpError as e:
                if is_workspace_miss(e):
                    continue
                if is_team_not_authorized(e):
                    invalidate(client)  # the cached workspace list was stale
                    continue
                return e.to_envelope()
            if isinstance(result, dict):
                result["workspace_id"] = candidate
            return dump_json_capped(annotate(result, scope))
        return error_envelope(
            "not_found",
            f"no doc page '{page_id}' in doc '{doc_id}' in any workspace this token can access",
            False,
            authorized_workspaces=scope.teams,
        )
