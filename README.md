# scottylabs-mcp

A Model Context Protocol (MCP) server that wraps the
[ScottyLabs CMU Courses](https://www.cmucourses.com) API
(`course-tools.apis.scottylabs.org`). It lets a Claude session search the
CMU course catalog and pull full course details from inside a chat.

## Tools

| Tool                       | Description                                                                  | Auth   |
| -------------------------- | ---------------------------------------------------------------------------- | ------ |
| `search_courses`           | Keyword/department search over the catalog. Paginated.                       | none   |
| `get_course`               | Full details for a single course (description, prereqs, schedules, etc.).    | none   |
| `get_course_schedules`     | Just the schedules for a course — smaller payload than `get_course`.         | none   |
| `get_instructor_schedules` | Schedules taught by a given instructor.                                      | none   |
| `get_requisites`           | Prereqs / postreqs / AND-of-ORs prereq relations for a course.               | none   |
| `get_geneds`               | Gen-ed-eligible courses for a school (SCS, CIT, MCS, Dietrich).              | none   |
| `search_instructors`       | Discover exact instructor name strings for the by-instructor tools.          | none   |
| `get_course_fces`          | FCE summary for a course (aggregates + 5 recent rows; `include_all=True` for full history). | gated  |
| `get_instructor_fces`      | FCE summary for an instructor across courses (same shape as above).          | gated  |

Wraps the public read endpoints of `course-tools.apis.scottylabs.org`
(the backend behind cmucourses.com and courses.scottylabs.org).

## Setup

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — provides
  the `uvx` runner used below. Install once and you're set.

### 1. Wire it into Claude Desktop

Edit `claude_desktop_config.json`:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Create the file if it doesn't exist. Add the `scottylabs-cmu-courses` entry
under `mcpServers` (merge with existing entries if present):

```json
{
  "mcpServers": {
    "scottylabs-cmu-courses": {
      "command": "uvx",
      "args": ["scottylabs-mcp"]
    }
  }
}
```

`uvx` fetches `scottylabs-mcp` from PyPI and runs it in an ephemeral
environment — no checkout, no manual install. Subsequent runs hit the uv
cache.

### 2. Restart Claude Desktop

Quit fully (system tray → Quit, not just close window) and reopen. In a
new chat, click the tools icon — you should see all 9
`scottylabs-cmu-courses` tools listed.

### 3. Try it in a chat

Public-endpoint examples (no auth required):

- "Search CMU courses for machine learning."
- "Show me the prereqs for 15-213."
- "What is Iliano Cervesato teaching this semester?"
- "List SCS gen-eds tagged Science."

### 4. (Optional) Enable FCE tools

`get_course_fces` and `get_instructor_fces` need a Clerk session JWT — see
[Auth (FCE tools only)](#auth-fce-tools-only) below.

### Claude Code instead of Desktop?

```bash
claude mcp add scottylabs-cmu-courses --scope user -- uvx scottylabs-mcp
```

Or paste the same `mcpServers` block into `~/.claude.json` under your
project entry.

### Local development

If you're hacking on the server, point Claude at your checkout instead:

```json
{
  "mcpServers": {
    "scottylabs-cmu-courses": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/scottylabs-mcp",
        "scottylabs-mcp"
      ]
    }
  }
}
```

Forward slashes in the path are JSON-safe on Windows. Restart Claude
Desktop to pick up code changes.

### Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Tools don't appear after restart | Check Claude Desktop's MCP log: `%APPDATA%\Claude\logs\mcp*.log` (Windows) or `~/Library/Logs/Claude/mcp*.log` (macOS). Most common: `uv` not on `PATH` for the GUI app. |
| `uvx` / `uv` not found in MCP log | Claude Desktop's GUI may not see your shell `PATH`. Run `where uvx` (Windows) / `which uvx` (Unix) and put the absolute path in `command`, e.g. `"C:/Users/you/AppData/Local/Python/pythoncore-3.12-64/Scripts/uvx.exe"`. |
| FCE tool 401s after running the auth helper | Clerk sessions expire (~7 days). Re-run `scottylabs-mcp-auth`. |
| Want to verify auth state | `uv run scottylabs-mcp-auth --show` — prints token-file path, presence, and env-var status. |
| Need to reset the saved token | `uv run scottylabs-mcp-auth --remove`. |
| Anything else broken | `uv run python scripts/smoke.py` from the project root validates all 13 cases against the live API without involving Claude. |

## Configuration

| Env var                  | Default                                       | Notes                                                 |
| ------------------------ | --------------------------------------------- | ----------------------------------------------------- |
| `SCOTTYLABS_API_BASE`    | `https://course-tools.apis.scottylabs.org`    | Override for local backend dev.                        |
| `SCOTTYLABS_AUTH_TOKEN`  | _(unset)_                                     | Static Clerk session JWT for FCE tools (advanced; bypasses cookie refresh). See Auth section. |

### Auth (FCE tools only)

`get_course_fces` and `get_instructor_fces` POST to `/fces`, which runs through
Clerk's `isUser` middleware. The production backend has auth enabled (verified
via the smoke harness — calls without a token come back 401), so the MCP
server needs to mint Clerk session JWTs.

Clerk session JWTs only live ~5 minutes, so the MCP server doesn't store a
JWT directly. Instead, it stores the long-lived `__client` cookie (~7-day TTL)
and exchanges it for a fresh JWT on each FCE call via Clerk's Frontend API.
Tokens are cached in-memory until shortly before they expire.

#### Option 1 (recommended): the helper

```bash
uv run --directory scottylabs-mcp scottylabs-mcp-auth
```

The helper:

1. Opens `https://www.cmucourses.com` in your browser.
2. Walks you through copying the **`__client` cookie** from DevTools.
   After sign-in you'll be redirected to `www.courses.scottylabs.org` —
   that's where the cookie lives (Application → Cookies →
   `https://www.courses.scottylabs.org` → `__client` → copy the Value).
   If it isn't there, also check `https://clerk.scottylabs.org`.
3. Saves the cookie to a per-user config file
   (`%APPDATA%\scottylabs-mcp\token` on Windows,
   `~/.config/scottylabs-mcp/token` elsewhere; `0o600` on Unix).

The MCP server picks it up automatically and refreshes JWTs as needed.
Manage it with:

```bash
scottylabs-mcp-auth --show     # check where it's stored / whether it's set
scottylabs-mcp-auth --remove   # delete the saved cookie
```

Re-run the helper when:

- FCE calls start returning auth errors (cookie expired, ~7 days).
- You sign out of cmucourses.com (cookie revoked).

#### Option 2: env var (advanced)

Set `SCOTTYLABS_AUTH_TOKEN` to a session JWT directly. The MCP server uses
this value verbatim — no refresh — so you'll need to keep it under 5 minutes
old. Mostly useful for one-off testing. This env var wins over the saved
cookie when both are set.

#### What happens without auth

The first FCE call returns a `ScottyLabsError` whose message tells the user
to run `scottylabs-mcp-auth`. No silent failure.

The other endpoints (search, get-course, schedules, requisites, geneds,
instructors) are public and need no auth.

## Smoke test

`scripts/smoke.py` calls the tool functions directly against the live API,
bypassing MCP transport. Useful for sanity checks during development.

```bash
uv run --directory scottylabs-mcp python scripts/smoke.py
```

Expects `Summary: 13/13 passed`.

## Layout

```
.
├── LICENSE
├── pyproject.toml
├── README.md
├── scripts/
│   └── smoke.py             # live-API harness, bypasses MCP transport
├── tests/
│   └── test_summarizer.py   # offline unit tests, run by CI
└── src/
    └── scottylabs_mcp/
        ├── __init__.py
        ├── __main__.py      # `python -m scottylabs_mcp`
        ├── auth_helper.py   # `scottylabs-mcp-auth` console script
        ├── clerk_auth.py    # Clerk Frontend API: cookie -> fresh JWT, with cache
        ├── client.py        # shared httpx.AsyncClient + error mapping
        ├── models.py        # pydantic types mirroring the upstream schema
        ├── server.py        # FastMCP app, tool registrations, entry point
        └── tools.py         # tool implementations (importable for tests)
```
