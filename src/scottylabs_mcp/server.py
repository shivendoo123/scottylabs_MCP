"""FastMCP server entry point.

`uvx scottylabs-mcp` (or `python -m scottylabs_mcp`) launches an MCP server
over stdio. Each tool is a thin wrapper that forwards to the implementations
in `tools.py` and converts upstream errors to readable strings for the LLM.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from scottylabs_mcp import client, tools
from scottylabs_mcp.models import (
    Course,
    CourseRequisites,
    CourseSearchResult,
    FCESummary,
    Gened,
    Schedule,
)

mcp = FastMCP("scottylabs-cmu-courses")


def _wrap(coro):  # pragma: no cover — trivial dispatcher
    """Run a tool coroutine and convert known errors to RuntimeError."""
    return coro


@mcp.tool()
async def search_courses(query: str, page: int = 1) -> CourseSearchResult:
    """Keyword-search the CMU course catalog.

    Use this when the user asks about a topic, department, or partial course
    name and you don't already have an exact course ID. The query is matched
    against name, department, description, and prereq string.

    Args:
        query: Free-text search. Examples: "machine learning", "discrete
            math", "Computer Science", "15-122". Department codes work too.
        page: 1-indexed page number. The backend caps page size at 10.

    Returns:
        Object with `totalDocs`, `totalPages`, `page`, and `docs` — a list of
        courses with `courseID`, `name`, `department`, `desc`, `units`,
        `prereqs`, etc.
    """

    try:
        return await tools.search_courses(query=query, page=page)
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_course(course_id: str) -> Course:
    """Fetch full details for a single CMU course, including current schedules.

    Use this when you already have the exact course ID. Accepts `"15-122"` or
    `"15122"`. Returns description, units, prereqs/coreqs, cross-listings,
    and upcoming schedule with lectures/sections.

    Args:
        course_id: CMU course ID, e.g. `"15-122"` or `"21-241"`.

    Returns:
        Course object with `name`, `department`, `desc`, `units`, `prereqs`,
        `coreqs`, `crosslisted`, `schedules`, etc.
    """

    try:
        return await tools.get_course(course_id=course_id)
    except client.CourseNotFoundError as e:
        raise RuntimeError(f"Course not found: {e}") from e
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_course_schedules(course_id: str) -> list[Schedule]:
    """Fetch lecture/section schedules for a single course.

    Prefer this over `get_course` when you only need meeting times — the
    response is much smaller. Returns one schedule per offered semester
    (typically several across recent years).

    Args:
        course_id: CMU course ID, e.g. `"15-122"`.

    Returns:
        List of Schedule objects.
    """

    try:
        return await tools.get_course_schedules(course_id=course_id)
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_instructor_schedules(instructor: str) -> list[Schedule]:
    """Fetch all schedules taught by the given instructor.

    Use this for "what is X teaching?" or to find classes by professor.
    Pass the instructor name *exactly* as it appears in the course data —
    use `search_instructors` first to discover the canonical spelling.

    Args:
        instructor: Instructor name, exact-match. Example: `"Iliano Cervesato"`.

    Returns:
        List of Schedule objects across all courses and semesters.
    """

    try:
        return await tools.get_instructor_schedules(instructor=instructor)
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_requisites(course_id: str) -> CourseRequisites:
    """Fetch the prerequisite / postrequisite graph for a course.

    Use this for "what do I need before X?" or "what unlocks after X?"
    questions. Returns:
    - `prereqs`: required courses (flat list).
    - `prereqRelations`: AND-of-ORs decoding (outer AND, inner OR).
    - `postreqs`: courses that list this one as a prereq.

    Args:
        course_id: CMU course ID, e.g. `"15-213"`.

    Returns:
        Object with `prereqs`, `prereqRelations`, `postreqs`.
    """

    try:
        return await tools.get_requisites(course_id=course_id)
    except client.CourseNotFoundError as e:
        raise RuntimeError(f"Course not found: {e}") from e
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_geneds(school: str) -> list[Gened]:
    """List gen-ed-eligible courses for a CMU school.

    Use this when the user wants courses satisfying a gen-ed requirement
    for their college.

    Args:
        school: Exactly one of `"SCS"` (School of Computer Science),
            `"CIT"` (engineering), `"MCS"` (sciences), or `"Dietrich"`
            (humanities and social sciences).

    Returns:
        List of Gened objects, each with course info, gen-ed `tags`, and
        a `startsCounting`/`stopsCounting` window.
    """

    try:
        return await tools.get_geneds(school=school)  # type: ignore[arg-type]
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def search_instructors(query: str | None = None, limit: int = 50) -> list[str]:
    """Look up CMU instructor names from the FCE roster.

    Use this to discover the exact spelling/casing of an instructor before
    calling `get_instructor_fces` or `get_instructor_schedules`. Names are
    exact-match — pass them verbatim downstream.

    Args:
        query: Optional case-insensitive substring filter (e.g. `"cervesato"`).
        limit: Max results, default 50, hard cap 200.

    Returns:
        List of instructor name strings.
    """

    try:
        return await tools.search_instructors(query=query, limit=limit)
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_course_fces(course_id: str, include_all: bool = False) -> FCESummary:
    """Fetch Faculty Course Evaluations (FCE) ratings for a course.

    Use this when the user asks about course difficulty, hours per week,
    or instructor ratings. Returns a compact summary: aggregates over all
    semesters plus the 5 most recent entries. Set `include_all=True` only
    when the user asks for the full history.

    Auth: requires the env var `SCOTTYLABS_AUTH_TOKEN` to be set to a valid
    Clerk JWT. If the upstream backend has auth disabled, the empty token
    will work too.

    Args:
        course_id: CMU course ID, e.g. `"15-122"`.
        include_all: Default `False` — `entries` holds the 5 most recent
            rows and `truncated` flags whether anything was cut. Pass
            `True` to populate `entries` with every row. Aggregates
            (`avg_hrs_per_week`, `avg_rating`, `years_covered`) always
            reflect the full dataset.

    Returns:
        `FCESummary` with `entry_count`, `years_covered`,
        `avg_hrs_per_week`, `avg_rating`, `entries`, `truncated`.
    """

    try:
        return await tools.get_course_fces(
            course_id=course_id, include_all=include_all
        )
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
async def get_instructor_fces(
    instructor: str, include_all: bool = False
) -> FCESummary:
    """Fetch Faculty Course Evaluations (FCE) ratings for an instructor.

    Use this for a professor's teaching record across courses, or to
    compare instructors. Returns a compact summary by default; aggregates
    span every semester they've taught.

    Auth: requires `SCOTTYLABS_AUTH_TOKEN` (see `get_course_fces`).

    Args:
        instructor: Instructor name, exact-match (use `search_instructors`).
        include_all: See `get_course_fces`. Default `False` keeps the
            response tight.

    Returns:
        `FCESummary` (see `get_course_fces`).
    """

    try:
        return await tools.get_instructor_fces(
            instructor=instructor, include_all=include_all
        )
    except (client.ScottyLabsError, ValueError) as e:
        raise RuntimeError(str(e)) from e


def main() -> None:
    """Entry point for `scottylabs-mcp` / `uvx scottylabs-mcp`."""
    try:
        mcp.run()
    finally:
        try:
            asyncio.run(client.aclose())
        except RuntimeError:
            # Event loop already closed; nothing to do.
            pass


if __name__ == "__main__":
    main()
