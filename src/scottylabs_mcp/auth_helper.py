"""Interactive auth helper for the FCE tools.

The FCE endpoint is gated by Clerk (third-party SaaS). Clerk session JWTs
expire after ~5 minutes, so a "paste a JWT" flow can't keep up. Instead,
this helper captures the long-lived `__client` cookie (~7-day TTL); the
MCP client uses it to mint short-lived JWTs on demand via Clerk's
Frontend API.

Run:
    scottylabs-mcp-auth          # save the __client cookie
    scottylabs-mcp-auth --show   # print where the cookie would be loaded from
    scottylabs-mcp-auth --remove # delete the saved cookie
"""

from __future__ import annotations

import argparse
import os
import sys
from getpass import getpass

from scottylabs_mcp.client import SIGN_IN_URL, token_file_path

INSTRUCTIONS = """
1) Sign in to cmucourses.com in the browser window that just opened.
   You'll be redirected to www.courses.scottylabs.org after sign-in.

2) Capture your Clerk `__client` cookie:

   - Press F12 to open DevTools.
   - Application tab -> Storage -> Cookies -> https://www.courses.scottylabs.org
     (the post-redirect domain; if missing, also try
     https://clerk.scottylabs.org).
   - Find the cookie named `__client`. Click it and copy the entire `Value`
     column. It's a long string, no surrounding quotes.

3) Paste the cookie value below. Input is hidden (no echo).

This cookie persists ~7 days. The MCP server uses it to refresh
short-lived session JWTs automatically — you won't re-paste until it
expires or you sign out.
"""


def _looks_like_clerk_cookie(s: str) -> bool:
    s = s.strip()
    # Clerk's __client cookie values are typically 200-1500+ chars and
    # base64-ish. Reject obvious mistakes (very short input, plain words).
    return len(s) >= 80 and " " not in s


def _open_browser() -> None:
    import webbrowser

    try:
        webbrowser.open(SIGN_IN_URL)
    except Exception:  # pragma: no cover — best-effort
        print(f"Could not auto-open browser. Please open {SIGN_IN_URL} manually.")


def _cmd_show() -> int:
    target = token_file_path()
    print(f"Token file path: {target}")
    if target.exists():
        try:
            size = target.stat().st_size
        except OSError:
            size = -1
        print(f"Status: present ({size} bytes)")
    else:
        print("Status: not present")
    env = os.environ.get("SCOTTYLABS_AUTH_TOKEN")
    if env:
        print("SCOTTYLABS_AUTH_TOKEN: set (overrides the file)")
    else:
        print("SCOTTYLABS_AUTH_TOKEN: not set")
    return 0


def _cmd_remove() -> int:
    target = token_file_path()
    if not target.exists():
        print(f"No token file at {target}; nothing to remove.")
        return 0
    try:
        target.unlink()
    except OSError as e:
        print(f"Failed to remove {target}: {e}", file=sys.stderr)
        return 1
    print(f"Removed {target}.")
    return 0


def _cmd_save() -> int:
    target = token_file_path()
    print(f"This will save a Clerk __client cookie to: {target}")
    if os.environ.get("SCOTTYLABS_AUTH_TOKEN"):
        print(
            "Warning: SCOTTYLABS_AUTH_TOKEN is set in your environment and will "
            "override anything saved here. Unset it if you want this file to take "
            "effect."
        )
    print(f"Opening {SIGN_IN_URL} in your default browser...")
    _open_browser()
    print(INSTRUCTIONS)

    # Strip a leading `__client=` if the user copy-pasted the whole assignment.
    try:
        cookie = getpass("__client cookie: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 1

    if cookie.startswith("__client="):
        cookie = cookie.split("=", 1)[1]
    cookie = cookie.strip().strip('"').strip("'")

    if not cookie:
        print("No cookie entered. Aborting.")
        return 1
    if not _looks_like_clerk_cookie(cookie):
        print(
            "Heads up: that doesn't look like a `__client` cookie value "
            "(expected a long base64-ish string with no spaces). Saving anyway "
            "— if FCE calls fail, re-run `scottylabs-mcp-auth`."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cookie, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        # Windows or restrictive FS — default ACLs already protect to user.
        pass

    print(f"\nSaved cookie to {target}.")
    print("The MCP server will use it to mint fresh JWTs on demand.")
    print(
        "To remove later: `scottylabs-mcp-auth --remove`, or just delete the file."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scottylabs-mcp-auth",
        description=(
            "Capture and save the Clerk __client cookie used to mint "
            "fresh session JWTs for the FCE tools."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--show",
        action="store_true",
        help="Print where the cookie would be loaded from and exit.",
    )
    group.add_argument(
        "--remove",
        action="store_true",
        help="Delete the saved cookie file.",
    )
    args = parser.parse_args()

    if args.show:
        return _cmd_show()
    if args.remove:
        return _cmd_remove()
    return _cmd_save()


if __name__ == "__main__":
    sys.exit(main())
