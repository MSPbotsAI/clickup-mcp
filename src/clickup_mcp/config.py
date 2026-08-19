from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport. Production/gateway deployments (Docker) serve HTTP, so that
    # is the default — per-request credentials arrive via the X-Clickup-Token
    # header and there is no env-var fallback on this path (see server.py's
    # get_client_from_context). stdio is opt-in, for local single-user tools
    # like Claude Desktop, where CLICKUP_API_TOKEN below is used instead.
    mcp_transport: Literal["stdio", "http"] = "http"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Local-dev-only credential. Only ever consulted when mcp_transport is
    # "stdio" (single process, single user, no gateway involved). The HTTP/
    # gateway transport path never reads this — it is header-only, by design,
    # so one tenant's request can never silently pick up another tenant's
    # (or the operator's own) token. See server.py::get_client_from_context.
    clickup_api_token: str | None = None
    clickup_base_url: str = "https://api.clickup.com/api/v2"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        HTTP/gateway transport always returns True — each request carries its
        own token via the X-Clickup-Token header, checked per-request by
        GatewayTokenMiddleware. stdio transport requires CLICKUP_API_TOKEN to
        be set at startup.
        """
        if self.mcp_transport == "http":
            return True
        return self.clickup_api_token is not None


def get_settings() -> Settings:
    return Settings()
