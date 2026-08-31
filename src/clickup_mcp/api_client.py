import asyncio
import base64
import hashlib
import time
from typing import Any

import httpx

from ._json import error_envelope

DEFAULT_BASE_URL = "https://api.clickup.com/api/v2"

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

# One shared connection pool for the process lifetime. No credentials are
# ever stored on it — the API token is passed per-request via headers, so
# this is safe to share across tenants/requests (see server.py's
# contextvar-based credential isolation, which is what actually keeps
# tenants apart).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    return _http_client


# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def _classify(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    return "invalid_argument", False


class ClickUpError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"ClickUp API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = _classify(self.status_code)
        return error_envelope(code, self.message, retryable)


class ClickUpClient:
    """Async httpx client wrapping the ClickUp REST API.

    Reuses the module-level connection pool (see _get_http_client) across
    every call made through this instance, rather than opening a new
    connection per request.
    """

    def __init__(self, api_token: str, base_url: str = DEFAULT_BASE_URL):
        self._token = api_token
        self._base_url = base_url.rstrip("/")
        # Cache keys derive from this, never from the token itself — see
        # tools/_teams.py for the one place tenant data is cached and why.
        self._fingerprint = hashlib.sha256(api_token.encode("utf-8")).hexdigest()[:16]

    @property
    def token_fingerprint(self) -> str:
        """Stable, non-reversible identifier for the credential in use."""
        return self._fingerprint

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
        return await self._request("GET", f"{self._base_url}{path}", params=params)

    async def get_v3(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", f"{self._v3_base_url()}{path}", params=params)

    async def post(self, path: str, body: Any = None, params: dict | None = None) -> Any:
        return await self._request(
            "POST", f"{self._base_url}{path}", params=params, json_body=body
        )

    async def put(self, path: str, body: Any = None, params: dict | None = None) -> Any:
        return await self._request("PUT", f"{self._base_url}{path}", params=params, json_body=body)

    async def delete(self, path: str, params: dict | None = None) -> Any:
        return await self._request("DELETE", f"{self._base_url}{path}", params=params)

    async def post_multipart(
        self, path: str, field_name: str, file_content_base64: str, filename: str, params: dict | None = None
    ) -> Any:
        content = base64.b64decode(file_content_base64)
        client = _get_http_client()
        url = f"{self._base_url}{path}"
        # No Content-Type here — httpx sets the multipart boundary itself.
        headers = {"Authorization": self._token}
        params = self._clean_params(params)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    url, headers=headers, params=params, files={field_name: (filename, content)}
                )
            except httpx.RequestError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                    continue
                raise ClickUpError(0, f"{e or type(e).__name__} (url={url})") from e

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(self._retry_delay(resp, attempt))
                continue

            self._raise_for_status(resp)
            return self._parse_body(resp)

        if last_exc:
            raise ClickUpError(0, f"{last_exc}") from last_exc
        raise ClickUpError(0, "request failed with no response")

    async def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: Any = None,
    ) -> Any:
        client = _get_http_client()
        headers = self._headers()
        params = self._clean_params(params)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.request(method, url, headers=headers, params=params, json=json_body)
            except httpx.RequestError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                    continue
                raise ClickUpError(0, f"{e or type(e).__name__} (url={url})") from e

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(self._retry_delay(resp, attempt))
                continue

            self._raise_for_status(resp)
            return self._parse_body(resp)

        # Unreachable in practice (loop always returns or raises above), but
        # keeps type checkers happy and guards against future edits.
        if last_exc:
            raise ClickUpError(0, f"{last_exc}") from last_exc
        raise ClickUpError(0, "request failed with no response")

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        # A generic Retry-After takes priority if present, but ClickUp's own
        # docs (developer.clickup.com/docs/rate-limits) only document
        # X-RateLimit-Reset on 429s — a Unix timestamp for when the
        # per-minute window resets, not a Retry-After header. Without this,
        # every 429 fell through to blind exponential backoff and ignored
        # the exact wait ClickUp already told us.
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        reset_at = resp.headers.get("X-RateLimit-Reset")
        if reset_at:
            try:
                delay = float(reset_at) - time.time()
                if delay > 0:
                    return min(delay, _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        return min(2**attempt, _MAX_BACKOFF_SECONDS)

    def _parse_body(self, resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json()
                if isinstance(detail, dict):
                    msg = detail.get("err") or detail.get("message") or detail.get("error") or str(detail)
                else:
                    msg = str(detail)
            except ValueError:
                msg = resp.text
            raise ClickUpError(resp.status_code, str(msg))
