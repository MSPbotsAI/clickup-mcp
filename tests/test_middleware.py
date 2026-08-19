"""Gateway credential middleware tests: missing-header 401, header values
correctly reaching the per-request contextvar (no global-state leakage
across requests), and — most importantly — proof that HTTP/gateway
transport never falls back to an env-var token when the header is absent.
"""

from starlette.testclient import TestClient

from clickup_mcp.__main__ import _build_http_app
from clickup_mcp.config import Settings
from clickup_mcp.server import create_mcp_server, get_client_from_context


def _make_app(**overrides):
    settings = Settings(**overrides)
    mcp = create_mcp_server(settings)
    return _build_http_app(mcp, settings), settings


def test_health_is_local_and_does_not_require_credentials():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_missing_header_returns_401_with_required_headers_listed():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "X-Clickup-Token" in body["required_headers"]


def test_missing_header_401s_even_when_env_var_token_is_set():
    """The critical regression test for this fix: previously, if the
    default auth_mode wasn't explicitly overridden to "gateway", the
    gateway middleware wasn't even installed, and a request with no header
    would silently use CLICKUP_API_TOKEN from the environment/settings —
    a cross-tenant credential leak. HTTP transport must now 401 on a
    missing header regardless of any env-var token configured on the
    process, because the middleware and header-only credential resolution
    are unconditional for HTTP transport (see server.py).
    """
    app, settings = _make_app(mcp_transport="http", clickup_api_token="pk_env_leaked_token")
    assert settings.clickup_api_token == "pk_env_leaked_token"  # sanity: env token IS configured
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401


def test_header_present_reaches_request_context():
    # Directly exercises the middleware's contextvar plumbing without a full
    # MCP protocol round-trip: confirms the header value that arrives on the
    # request is exactly what get_client_from_context sees, and that it's
    # reset afterward (no leakage to the next request).
    import asyncio

    from clickup_mcp.server import GatewayTokenMiddleware, _gateway_token_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["token"] = _gateway_token_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [(b"x-clickup-token", b"test-token-123")],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["token"] == "test-token-123"
    # After the request completes, the contextvar must be reset — a fresh
    # get() outside any request context sees no leftover credential.
    assert _gateway_token_var.get() is None


def test_client_factory_returns_none_without_context():
    settings = Settings(mcp_transport="http")
    assert get_client_from_context(settings) is None


def test_client_factory_returns_none_even_with_env_token_in_http_mode():
    """Same regression as above, at the unit level: get_client_from_context
    must ignore settings.clickup_api_token entirely when mcp_transport is
    "http", even if it happens to be set."""
    settings = Settings(mcp_transport="http", clickup_api_token="pk_env_leaked_token")
    assert get_client_from_context(settings) is None


def test_client_factory_uses_env_token_in_stdio_mode():
    """stdio transport (local dev only, no gateway) is the one legitimate
    place an env-var token is used."""
    settings = Settings(mcp_transport="stdio", clickup_api_token="pk_local_dev_token")
    client = get_client_from_context(settings)
    assert client is not None
    assert client._token == "pk_local_dev_token"
