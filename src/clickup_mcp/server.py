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
# Per-request token contextvar for gateway mode.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# ─────────────────────────────────────────────────────────────────────────────
_gateway_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "clickup_gateway_token", default=None
)


def get_client_from_context(settings: Settings) -> ClickUpClient | None:
    """Resolve the active ClickUpClient for the current request context."""
    if settings.auth_mode == "gateway":
        token = _gateway_token_var.get()
    else:
        token = settings.clickup_api_token

    if not token:
        return None
    return ClickUpClient(token, settings.clickup_base_url)


class GatewayTokenMiddleware:
    """ASGI middleware for gateway mode.

    Reads X-Clickup-Token from request headers and stores it in the contextvar.
    Returns 401 if the header is missing on /mcp requests.
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
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], ClickUpClient | None] = lambda: get_client_from_context(settings)

    if not settings.has_credentials:
        # Graceful degradation: register only a diagnostic tool when no credentials
        @mcp.tool()
        async def clickup_test_connection() -> str:
            """Test ClickUp connection. Shows configuration requirements when credentials are missing."""
            return (
                "Error: Missing ClickUp credentials.\n\n"
                "Set the required environment variable:\n"
                "  CLICKUP_API_TOKEN=pk_xxxxx\n\n"
                "Or use gateway mode (per-request token):\n"
                "  AUTH_MODE=gateway\n"
                "  Send header: X-Clickup-Token: pk_xxxxx"
            )

        print(
            "Warning: No ClickUp credentials found. Only the diagnostic tool is available.",
            file=sys.stderr,
        )
        return mcp

    # Import and register all tool domains
    from .tools import comments, folders, lists, spaces, tasks, workspaces

    workspaces.register(mcp, client_factory)
    spaces.register(mcp, client_factory)
    folders.register(mcp, client_factory)
    lists.register(mcp, client_factory)
    tasks.register(mcp, client_factory)
    comments.register(mcp, client_factory)

    return mcp
