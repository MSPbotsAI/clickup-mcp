import contextvars
import sys
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import ClickUpClient
from .config import Settings

# ─────────────────────────────────────────────────────────────────────────────
# Per-request token contextvar for HTTP/gateway transport.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# ─────────────────────────────────────────────────────────────────────────────
_gateway_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "clickup_gateway_token", default=None
)


def get_client_from_context(settings: Settings) -> ClickUpClient | None:
    """Resolve the active ClickUpClient for the current request.

    HTTP/gateway transport: the token comes ONLY from the per-request
    contextvar populated by GatewayTokenMiddleware, which itself 401s any
    request missing the X-Clickup-Token header. There is deliberately no
    fallback to an env-var token on this path — a request with no header
    must fail closed, never silently borrow another tenant's (or the
    operator's own) credentials.

    stdio transport (local dev only, e.g. Claude Desktop): single process,
    single user, no gateway involved — the token comes from
    settings.clickup_api_token (CLICKUP_API_TOKEN).
    """
    if settings.mcp_transport == "http":
        token = _gateway_token_var.get()
    else:
        token = settings.clickup_api_token

    if not token:
        return None
    return ClickUpClient(token, settings.clickup_base_url)


class GatewayTokenMiddleware:
    """ASGI middleware for HTTP/gateway transport.

    Reads X-Clickup-Token from request headers and stores it in the
    contextvar. Returns 401 if the header is missing on /mcp requests. There
    is no other way for a request handled through this middleware to obtain
    a token — see get_client_from_context.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        token = request.headers.get("x-clickup-token")
        if not token:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": "Gateway mode requires the X-Clickup-Token header",
                    "required_headers": ["X-Clickup-Token"],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_token_var.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_token_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # The container runs on an internal docker network behind mcp-gateway, which
    # forwards requests with Host: clickup-mcp:8080. The MCP SDK's DNS-rebinding
    # protection (a browser-oriented safeguard) rejects that host with 421
    # Misdirected Request, so disable it — the container is never exposed publicly.
    mcp = FastMCP(
        name="clickup-mcp",
        instructions=(
            "ClickUp is a project/task management platform. Tool categories: "
            "tasks (clickup_get_task, clickup_search_tasks, clickup_create_task, "
            "clickup_update_task, clickup_delete_task, clickup_move_task) for the "
            "core work-item CRUD; lists/folders/spaces (clickup_get_list, "
            "clickup_create_list_in_folder, clickup_create_folderless_list, "
            "clickup_update_list, clickup_get_folder, clickup_get_folder_lists, "
            "clickup_create_folder, clickup_update_folder, clickup_delete_folder, "
            "clickup_get_space, clickup_get_space_folders, clickup_get_space_lists) "
            "for the containment hierarchy Workspace > Space > Folder > List > Task; "
            "workspaces/people (clickup_get_workspaces, clickup_list_spaces, "
            "clickup_list_members, clickup_list_tasks_for_person) for org-wide "
            "discovery and resolving a person to a user_id for assignment/filtering; "
            "comments (clickup_get_task_comments, clickup_create_task_comment) for "
            "task discussion; docs (clickup_get_doc_page) for ClickUp Docs content; "
            "attachments (clickup_attach_task_file, clickup_create_comment_with_image) "
            "for uploading files and posting inline images; and rocks "
            "(clickup_list_rocks_for_org) for EOS quarterly-goal reporting. "
            "Workspace/team IDs resolve from the API token: omit team_id unless the "
            "user named a specific workspace. Typical flow: clickup_search_tasks or "
            "clickup_list_tasks_for_person to find work, then the task/comment/"
            "attachment tools to act on it. clickup_delete_task and "
            "clickup_delete_folder are destructive and require confirm=true."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], ClickUpClient | None] = lambda: get_client_from_context(settings)

    if not settings.has_credentials:
        # Graceful degradation: register only a diagnostic tool when no credentials
        # (stdio transport only — HTTP/gateway transport always has_credentials=True).
        @mcp.tool()
        async def clickup_test_connection() -> str:
            """Test ClickUp connection. Shows configuration requirements when credentials are missing."""
            return (
                "Error: Missing ClickUp credentials.\n\n"
                "Set the required environment variable:\n"
                "  CLICKUP_API_TOKEN=pk_xxxxx\n\n"
                "Or run with MCP_TRANSPORT=http (the default) behind the gateway, "
                "sending header: X-Clickup-Token: pk_xxxxx"
            )

        print(
            "Warning: No ClickUp credentials found. Only the diagnostic tool is available.",
            file=sys.stderr,
        )
        return mcp

    # Import and register all tool domains
    from .tools import attachments, comments, docs, folders, lists, people, rocks, spaces, tasks, workspaces

    workspaces.register(mcp, client_factory)
    spaces.register(mcp, client_factory)
    folders.register(mcp, client_factory)
    lists.register(mcp, client_factory)
    tasks.register(mcp, client_factory)
    people.register(mcp, client_factory)
    rocks.register(mcp, client_factory)
    comments.register(mcp, client_factory)
    docs.register(mcp, client_factory)
    attachments.register(mcp, client_factory)

    return mcp
