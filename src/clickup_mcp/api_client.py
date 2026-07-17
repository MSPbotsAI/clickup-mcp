from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.clickup.com/api/v2"


class ClickUpError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"ClickUp API error {status_code}: {message}")


class ClickUpClient:
    """Async httpx client wrapping the ClickUp REST API."""

    def __init__(self, api_token: str, base_url: str = DEFAULT_BASE_URL):
        self._token = api_token
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        # ClickUp uses bare token in Authorization header (no "Bearer" prefix)
        return {
            "Authorization": self._token,
            "Content-Type": "application/json",
        }

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    def _v3_base_url(self) -> str:
        # Most endpoints are v2, but a few (e.g. Docs pages) live under v3.
        # Derive the v3 base from the configured base by swapping a trailing /v2.
        if self._base_url.endswith("/v2"):
            return self._base_url[: -len("/v2")] + "/v3"
        return self._base_url

    async def get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=self._clean_params(params),
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    async def get_v3(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._v3_base_url()}{path}",
                headers=self._headers(),
                params=self._clean_params(params),
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    async def post(self, path: str, body: Any = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}{path}",
                headers=self._headers(),
                json=body,
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    async def put(self, path: str, body: Any = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self._base_url}{path}",
                headers=self._headers(),
                json=body,
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    async def delete(self, path: str) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._base_url}{path}",
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 else None

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise ClickUpError(resp.status_code, str(detail))
