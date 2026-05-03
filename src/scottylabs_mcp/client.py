"""HTTP client for the ScottyLabs course-tools backend.

A single shared `httpx.AsyncClient` is held at module scope so connections are
pooled across MCP tool calls. The client is created lazily on first use and
closed when the server exits.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API_BASE = "https://course-tools.apis.scottylabs.org"
SIGN_IN_URL = "https://www.cmucourses.com"


def get_api_base() -> str:
    return os.environ.get("SCOTTYLABS_API_BASE", DEFAULT_API_BASE).rstrip("/")


def token_file_path() -> Path:
    """Per-user config path where `scottylabs-mcp-auth` persists the JWT."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "scottylabs-mcp" / "token"


def _read_token_file() -> str:
    path = token_file_path()
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def has_auth_credentials() -> bool:
    """Cheap, sync check for whether any auth source is configured."""
    return bool(os.environ.get("SCOTTYLABS_AUTH_TOKEN") or _read_token_file())


async def get_auth_token() -> str:
    """Return a fresh Clerk session JWT for the FCE endpoint.

    Resolution order:
    1. `SCOTTYLABS_AUTH_TOKEN` env var — used as-is. Useful for testing or
       when the user wants to bring their own short-lived JWT.
    2. Token file written by `scottylabs-mcp-auth` — treated as a Clerk
       `__client` cookie value and exchanged for a fresh session JWT via
       Clerk's Frontend API. The fresh JWT is cached in-memory until
       shortly before its `exp`.
    3. Empty string when no credentials are configured.

    Raises:
        ScottyLabsError: If a saved cookie is present but Clerk's API
            rejects it (cookie expired, session revoked, network error).
    """
    env = os.environ.get("SCOTTYLABS_AUTH_TOKEN")
    if env:
        return env.strip()

    cookie = _read_token_file()
    if not cookie:
        return ""

    # Avoid circular import at module load.
    from scottylabs_mcp import clerk_auth

    try:
        return await clerk_auth.refresh_jwt(cookie, get_client())
    except clerk_auth.ClerkAuthError as e:
        raise ScottyLabsError(str(e)) from e


class ScottyLabsError(Exception):
    """Raised for errors that should be surfaced to the LLM caller."""


class CourseNotFoundError(ScottyLabsError):
    """Course ID was not found by the upstream API."""


_client: httpx.AsyncClient | None = None


def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=get_api_base(),
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={
            "Accept": "application/json",
            "User-Agent": "scottylabs-mcp/0.1.0 (+https://github.com/ScottyLabs/cmucourses)",
        },
    )


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _handle_response(resp: httpx.Response) -> Any:
    """Translate upstream status codes into typed errors, then return JSON.

    The backend has a few quirks worth centralizing here:
    - Missing courses on `/course/:id` come back as 500 with a Prisma
      `NotFoundError` body.
    - `/courses/requisites/:id` is the only endpoint that returns a real
      400 for missing courses, with body `{"error": "Course not found"}`.
    - `/fces` (POST, auth-gated) returns 401 with a plain-text body when
      the Clerk JWT is missing or invalid.
    """
    path = str(resp.request.url.path) if resp.request else "<unknown>"

    if resp.status_code == 401:
        raise ScottyLabsError(
            "Upstream rejected the request (401). The FCE endpoint requires "
            "a Clerk JWT. Run `scottylabs-mcp-auth` once to capture and save "
            f"your token (it opens {SIGN_IN_URL} and walks you through it), "
            "or set SCOTTYLABS_AUTH_TOKEN manually. See the README for details."
        )

    if resp.status_code == 400:
        body_text = resp.text
        if "Course not found" in body_text:
            raise CourseNotFoundError(
                f"Not found at {path}: {body_text[:200]}"
            )
        raise ScottyLabsError(f"Bad request to {path}: {body_text[:200]}")

    if resp.status_code == 404:
        raise CourseNotFoundError(f"Not found: {path}")

    if resp.status_code == 500:
        body_text = resp.text
        if "NotFoundError" in body_text or "No courses found" in body_text:
            raise CourseNotFoundError(
                f"No record found for {path}. Upstream said: {body_text[:200]}"
            )
        raise ScottyLabsError(f"Upstream 500 on {path}: {body_text[:200]}")

    resp.raise_for_status()
    return resp.json()


async def get_json(
    path: str,
    params: list[tuple[str, str]] | dict[str, Any] | None = None,
) -> Any:
    """GET `path`, return decoded JSON. Errors mapped to `ScottyLabsError`
    subclasses with a friendly message."""

    client = get_client()
    try:
        resp = await client.get(path, params=params)
    except httpx.TimeoutException as e:
        raise ScottyLabsError(
            f"Request to {get_api_base()}{path} timed out: {e}"
        ) from e
    except httpx.HTTPError as e:
        raise ScottyLabsError(
            f"Network error talking to {get_api_base()}{path}: {e}"
        ) from e

    return _handle_response(resp)


async def post_json(
    path: str,
    params: list[tuple[str, str]] | dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """POST `path` with a JSON body; same error mapping as `get_json`."""

    client = get_client()
    try:
        resp = await client.post(
            path,
            params=params,
            json=json_body if json_body is not None else {},
            headers={"Content-Type": "application/json"},
        )
    except httpx.TimeoutException as e:
        raise ScottyLabsError(
            f"Request to {get_api_base()}{path} timed out: {e}"
        ) from e
    except httpx.HTTPError as e:
        raise ScottyLabsError(
            f"Network error talking to {get_api_base()}{path}: {e}"
        ) from e

    return _handle_response(resp)
