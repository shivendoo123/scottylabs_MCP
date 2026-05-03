"""Clerk Frontend API client for refreshing session JWTs on demand.

The CMU Courses backend's FCE endpoint expects a Clerk-issued RS256 JWT.
Clerk session JWTs live ~5 minutes, so we can't ship a static token —
this module exchanges the long-lived `__client` cookie (~7-day TTL) for
fresh session JWTs as needed and caches them in-memory until shortly
before they expire.

This reverse-engineers Clerk's Frontend API. Endpoints used:
  GET  https://clerk.scottylabs.org/v1/client                 -> session id
  POST https://clerk.scottylabs.org/v1/client/sessions/{sid}/tokens -> jwt

Both authenticated via the `__client` cookie. No officially-public client
library covers this flow; if Clerk ever changes the shape, expect to
update here.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

import httpx

CLERK_API_BASE = "https://clerk.scottylabs.org"
CLERK_JS_VERSION = "5.0.0"
REFRESH_BUFFER_SECONDS = 30


class ClerkAuthError(Exception):
    """Raised when Clerk's Frontend API rejects our request."""


@dataclass
class _CachedToken:
    jwt: str
    exp: int


_token_cache: dict[str, _CachedToken] = {}
_session_id_cache: dict[str, str] = {}


def _decode_jwt_exp(jwt: str) -> int:
    """Return the `exp` claim from a JWT, or 0 if not parseable."""
    parts = jwt.split(".")
    if len(parts) != 3:
        return 0
    try:
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return int(payload.get("exp", 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0


async def _bootstrap_session_id(
    http_client: httpx.AsyncClient, cookie: str
) -> str:
    """Fetch the active session id for this client cookie. Cached."""
    if cookie in _session_id_cache:
        return _session_id_cache[cookie]

    r = await http_client.get(
        f"{CLERK_API_BASE}/v1/client",
        params={"_clerk_js_version": CLERK_JS_VERSION},
        cookies={"__client": cookie},
    )
    if r.status_code != 200:
        raise ClerkAuthError(
            f"Clerk bootstrap failed ({r.status_code}): {r.text[:200]}"
        )

    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError) as e:
        raise ClerkAuthError(f"Clerk bootstrap returned non-JSON: {e}") from e

    payload = body.get("response") if isinstance(body.get("response"), dict) else body
    sid = payload.get("last_active_session_id")
    if not sid:
        for session in payload.get("sessions") or []:
            if isinstance(session, dict) and session.get("status") == "active":
                sid = session.get("id")
                break

    if not sid:
        raise ClerkAuthError(
            "No active Clerk session found for the saved __client cookie. "
            "Sign in to cmucourses.com again and re-run scottylabs-mcp-auth."
        )

    _session_id_cache[cookie] = sid
    return sid


async def refresh_jwt(cookie: str, http_client: httpx.AsyncClient) -> str:
    """Return a fresh session JWT for the given __client cookie.

    Caches the JWT in-memory until ~30s before its `exp`. On cache miss,
    bootstraps the session id once (also cached) and POSTs to Clerk's
    tokens endpoint.

    Raises ClerkAuthError if the cookie or session is rejected.
    """
    cookie = cookie.strip()
    if not cookie:
        raise ClerkAuthError("No __client cookie provided.")

    now = int(time.time())
    cached = _token_cache.get(cookie)
    if cached and cached.exp - REFRESH_BUFFER_SECONDS > now:
        return cached.jwt

    sid = await _bootstrap_session_id(http_client, cookie)

    r = await http_client.post(
        f"{CLERK_API_BASE}/v1/client/sessions/{sid}/tokens",
        params={"_clerk_js_version": CLERK_JS_VERSION},
        cookies={"__client": cookie},
    )
    if r.status_code != 200:
        # The cached session id may have rotated; drop it so the next attempt
        # re-bootstraps.
        _session_id_cache.pop(cookie, None)
        if r.status_code in (401, 403, 404):
            raise ClerkAuthError(
                f"Clerk rejected the __client cookie ({r.status_code}). "
                "Re-run `scottylabs-mcp-auth` to capture a fresh cookie."
            )
        raise ClerkAuthError(
            f"Clerk token refresh failed ({r.status_code}): {r.text[:200]}"
        )

    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError) as e:
        raise ClerkAuthError(f"Clerk tokens endpoint returned non-JSON: {e}") from e

    jwt = body.get("jwt") if isinstance(body, dict) else None
    if not jwt:
        raise ClerkAuthError(
            f"Clerk response missing 'jwt' field: {str(body)[:200]}"
        )

    exp = _decode_jwt_exp(jwt) or (now + 60)
    _token_cache[cookie] = _CachedToken(jwt=jwt, exp=exp)
    return jwt


def clear_cache() -> None:
    """Drop all cached tokens and session ids. Useful for tests."""
    _token_cache.clear()
    _session_id_cache.clear()
