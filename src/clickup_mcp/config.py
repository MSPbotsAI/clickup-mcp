from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Auth mode
    auth_mode: Literal["env", "gateway"] = "env"

    # ClickUp credentials (only required in env mode)
    clickup_api_token: str | None = None
    clickup_base_url: str = "https://api.clickup.com/api/v2"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        Gateway mode always returns True — each request carries its own token.
        Env mode requires CLICKUP_API_TOKEN to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return self.clickup_api_token is not None


def get_settings() -> Settings:
    return Settings()
