"""Tool implementations.

Pure-async functions, importable from tests / smoke scripts as well as the
FastMCP server module. Each function returns a typed `pydantic` model so the
serialization is consistent whether MCP, JSON, or repl print.
"""

from __future__ import annotations

import re
from typing import Literal

from scottylabs_mcp.client import (
    CourseNotFoundError,
    ScottyLabsError,
    get_auth_token,
    get_json,
    post_json,
)
from scottylabs_mcp.models import (
    Course,
    CourseRequisites,
    CourseSearchResult,
    FCE,
    FCESummary,
    Gened,
    Schedule,
)

_FCE_RECENT_LIMIT = 5
_SEMESTER_ORDER = {"fall": 3, "summer": 2, "spring": 1}

_COURSE_ID_RE = re.compile(r"^\d{2}-?\d{3}$")
GENED_SCHOOLS = ("SCS", "CIT", "MCS", "Dietrich")
School = Literal["SCS", "CIT", "MCS", "Dietrich"]
_INSTRUCTORS_HARD_MAX = 200


def _normalize_course_id(course_id: str) -> str:
    """Mirror the backend's `standardizeID`: insert dash for `XXYYY` → `XX-YYY`.
    Raises `ValueError` when the input is clearly not a CMU course ID."""

    cleaned = course_id.strip()
    if not _COURSE_ID_RE.match(cleaned):
        raise ValueError(
            f"Invalid CMU course ID '{course_id}'. Expected formats: '15-122' or '15122'."
        )
    if "-" not in cleaned and len(cleaned) >= 5:
        cleaned = cleaned[:2] + "-" + cleaned[2:]
    return cleaned


def _require_nonempty(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


async def search_courses(query: str, page: int = 1) -> CourseSearchResult:
    """Keyword-search the CMU course catalog.

    Use this when the user asks about a topic, department code, or partial
    course name and you don't already have an exact course ID. The query is
    matched against `name`, `department`, `desc`, and `prereqString` via Mongo
    full-text search; results are ranked by relevance.

    Args:
        query: Free-text search. Examples: "machine learning",
            "discrete math", "15-122", "Computer Science". Department codes
            like "CS" work as keywords (the search index covers `department`).
        page: 1-indexed page number. The backend caps page size at 10, so
            paginate when you need more.

    Returns:
        `CourseSearchResult` with `totalDocs`, `totalPages`, `page`, and
        `docs` (list of `Course`). Each `Course` includes `courseID`,
        `name`, `department`, `desc`, `units`, `prereqs`, etc.

    Raises:
        ScottyLabsError: Network failure or upstream error.
    """

    if page < 1:
        raise ValueError("page must be >= 1")
    query = _require_nonempty(query, "query")

    params: list[tuple[str, str]] = [
        ("page", str(page)),
        ("keywords", query),
    ]
    data = await get_json("/courses/search", params=params)
    return CourseSearchResult.model_validate(data)


async def get_course(course_id: str) -> Course:
    """Fetch full details for a single CMU course, including current schedule.

    Use this when you have the exact course ID (from prior search results or
    the user). The response includes the description, units, prereqs/coreqs,
    cross-listings, and embedded `schedules` for upcoming offerings.

    Args:
        course_id: CMU course ID. Accepts `"15-122"` or `"15122"`; the dashed
            form is canonical. Examples: `"15-122"`, `"21-241"`, `"36-201"`.

    Returns:
        `Course` model with all fields populated, including `schedules`.

    Raises:
        CourseNotFoundError: No course with that ID exists.
        ScottyLabsError: Network failure or other upstream error.
        ValueError: `course_id` is not in a CMU format.
    """

    normalized = _normalize_course_id(course_id)
    try:
        data = await get_json(
            f"/course/{normalized}",
            params=[("schedules", "true")],
        )
    except CourseNotFoundError as e:
        raise CourseNotFoundError(
            f"Course '{course_id}' (normalized: '{normalized}') not found."
        ) from e
    return Course.model_validate(data)


async def get_course_schedules(course_id: str) -> list[Schedule]:
    """Fetch the schedule (lectures, sections, times) for a single course.

    Prefer this over `get_course` when you only need meeting times — the
    response is much smaller. Returns one `Schedule` per offered semester
    (typically several across recent years).

    Args:
        course_id: CMU course ID, e.g. `"15-122"`.

    Returns:
        List of `Schedule` objects. Empty list if the course has no
        recorded schedules.

    Raises:
        ScottyLabsError: Network failure or upstream error.
        ValueError: `course_id` is not in a CMU format.
    """

    normalized = _normalize_course_id(course_id)
    data = await get_json(
        "/schedules", params=[("courseID", normalized)]
    )
    if not isinstance(data, list):
        return []
    return [Schedule.model_validate(item) for item in data]


async def get_instructor_schedules(instructor: str) -> list[Schedule]:
    """Fetch all schedules taught by the given instructor.

    Use this when the user asks "what is X teaching?" or wants to find
    classes by professor.

    Args:
        instructor: Instructor name *exactly* as it appears in the course
            data — pass values from `search_instructors` verbatim. The
            upstream match is exact-string and case-sensitive.

    Returns:
        List of `Schedule` objects (across all courses and semesters).
        Empty list if no schedules match.

    Raises:
        ScottyLabsError: Network failure or upstream error.
        ValueError: `instructor` is empty.
    """

    instructor = _require_nonempty(instructor, "instructor")
    data = await get_json(
        "/schedules", params=[("instructor", instructor)]
    )
    if not isinstance(data, list):
        return []
    return [Schedule.model_validate(item) for item in data]


async def get_requisites(course_id: str) -> CourseRequisites:
    """Fetch the prerequisite / postrequisite graph for a course.

    Use this to answer "what do I need before taking X?" or "what unlocks
    after X?" questions. Returns three lists:
    - `prereqs`: required courses (flat list).
    - `prereqRelations`: AND-of-ORs decoding — outer list joined by AND,
      inner lists by OR.
    - `postreqs`: courses that list this one as a prereq.

    Args:
        course_id: CMU course ID, e.g. `"15-213"`.

    Returns:
        `CourseRequisites` with `prereqs`, `prereqRelations`, `postreqs`.

    Raises:
        CourseNotFoundError: No course with that ID exists.
        ScottyLabsError: Network failure or other upstream error.
        ValueError: `course_id` is not in a CMU format.
    """

    normalized = _normalize_course_id(course_id)
    try:
        data = await get_json(f"/courses/requisites/{normalized}")
    except CourseNotFoundError as e:
        raise CourseNotFoundError(
            f"Course '{course_id}' (normalized: '{normalized}') not found."
        ) from e
    return CourseRequisites.model_validate(data)


async def get_geneds(school: School) -> list[Gened]:
    """List gen-ed-eligible courses for a given CMU school.

    Use this when the user wants to find courses that satisfy a gen-ed
    requirement for their college.

    Args:
        school: Exactly one of `"SCS"` (School of Computer Science),
            `"CIT"` (Carnegie Institute of Technology / Engineering),
            `"MCS"` (Mellon College of Science), or `"Dietrich"`
            (Dietrich College of Humanities and Social Sciences).

    Returns:
        List of `Gened` objects. Each entry includes the course ID,
        name, units, description, gen-ed `tags`, and the
        `startsCounting`/`stopsCounting` window.

    Raises:
        ValueError: `school` is not in the allowed set.
        ScottyLabsError: Network failure or upstream error.
    """

    if school not in GENED_SCHOOLS:
        raise ValueError(
            f"Invalid school '{school}'. Must be one of: {', '.join(GENED_SCHOOLS)}."
        )
    data = await get_json("/geneds", params=[("school", school)])
    if not isinstance(data, list):
        return []
    return [Gened.model_validate(item) for item in data]


async def search_instructors(
    query: str | None = None, limit: int = 50
) -> list[str]:
    """Look up CMU instructor names from the FCE roster.

    Returns distinct instructor names. Use this to discover the exact
    spelling/casing before calling `get_instructor_fces` or
    `get_instructor_schedules`.

    Args:
        query: Optional case-insensitive substring filter. When omitted,
            returns the first `limit` names alphabetically (the upstream
            sort).
        limit: Cap on returned names. Default 50, hard maximum 200 to
            keep responses LLM-context-friendly.

    Returns:
        List of instructor name strings, e.g. `["Iliano Cervesato", ...]`.
        Names are exact-match strings — pass them verbatim to other
        instructor-keyed tools.

    Raises:
        ValueError: `limit` is non-positive or above the hard max.
        ScottyLabsError: Network failure or upstream error.
    """

    if limit <= 0:
        raise ValueError("limit must be >= 1")
    if limit > _INSTRUCTORS_HARD_MAX:
        raise ValueError(
            f"limit must be <= {_INSTRUCTORS_HARD_MAX} (got {limit})"
        )

    data = await get_json("/instructors")
    if not isinstance(data, list):
        return []

    names: list[str] = []
    for item in data:
        if isinstance(item, dict):
            name = item.get("instructor")
            if isinstance(name, str) and name:
                names.append(name)

    if query is not None:
        needle = query.strip().lower()
        if needle:
            names = [n for n in names if needle in n.lower()]

    return names[:limit]


async def _post_fces(params: list[tuple[str, str]]) -> list[FCE]:
    token = await get_auth_token()
    body = {"token": token}
    try:
        data = await post_json("/fces", params=params, json_body=body)
    except CourseNotFoundError:
        return []
    if not isinstance(data, list):
        return []
    return [FCE.model_validate(item) for item in data]


def _safe_year(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _fce_sort_key(f: FCE) -> tuple[int, int]:
    year = _safe_year(f.year) or 0
    semester = (f.semester or "").lower() if isinstance(f.semester, str) else ""
    return (year, _SEMESTER_ORDER.get(semester, 0))


def _avg_rating(rating_lists: list[list[float]]) -> list[float] | None:
    """Element-wise mean across the per-question rating arrays."""
    valid = [r for r in rating_lists if r]
    if not valid:
        return None
    max_len = max(len(r) for r in valid)
    sums = [0.0] * max_len
    counts = [0] * max_len
    for r in valid:
        for i, v in enumerate(r):
            if isinstance(v, (int, float)):
                sums[i] += float(v)
                counts[i] += 1
    return [round(sums[i] / counts[i], 2) if counts[i] else 0.0 for i in range(max_len)]


def _summarize_fces(fces: list[FCE], include_all: bool) -> FCESummary:
    sorted_fces = sorted(fces, key=_fce_sort_key, reverse=True)
    entry_count = len(sorted_fces)

    years = sorted(
        {y for f in sorted_fces if (y := _safe_year(f.year)) is not None},
        reverse=True,
    )

    hrs_values = [
        float(f.hrsPerWeek) for f in sorted_fces
        if isinstance(f.hrsPerWeek, (int, float))
    ]
    avg_hrs = round(sum(hrs_values) / len(hrs_values), 2) if hrs_values else None

    avg_rating = _avg_rating([f.rating for f in sorted_fces])

    if include_all:
        entries = sorted_fces
        truncated = False
    else:
        entries = sorted_fces[:_FCE_RECENT_LIMIT]
        truncated = entry_count > _FCE_RECENT_LIMIT

    return FCESummary(
        entry_count=entry_count,
        years_covered=years,
        avg_hrs_per_week=avg_hrs,
        avg_rating=avg_rating,
        entries=entries,
        truncated=truncated,
    )


async def get_course_fces(course_id: str, include_all: bool = False) -> FCESummary:
    """Fetch Faculty Course Evaluations (FCE) ratings for a course.

    Use this when the user asks about course difficulty, hours per week,
    or instructor ratings. Returns a compact summary by default — payloads
    for popular courses can otherwise span dozens of semesters.

    **Auth required.** This endpoint runs through Clerk's `isUser`
    middleware on the backend. If the upstream production server has
    `AUTH_ENABLED=true`, you must set `SCOTTYLABS_AUTH_TOKEN` to a valid
    Clerk JWT or this tool will raise a `ScottyLabsError` mentioning the
    env var.

    Args:
        course_id: CMU course ID, e.g. `"15-122"`.
        include_all: When `False` (default), `entries` holds the 5 most
            recent rows (sorted by year, semester desc) and `truncated`
            tells you whether more were cut. When `True`, `entries`
            holds every row.

    Returns:
        `FCESummary` with `entry_count`, `years_covered`, `avg_hrs_per_week`,
        `avg_rating` (element-wise mean of the per-question rating array),
        `entries`, and `truncated`. Aggregates always reflect the full
        dataset, even when `entries` is capped.

    Raises:
        ScottyLabsError: Network failure, 401 (auth missing/invalid),
            or other upstream error.
        ValueError: `course_id` is not in a CMU format.
    """

    normalized = _normalize_course_id(course_id)
    fces = await _post_fces([("courseID", normalized)])
    return _summarize_fces(fces, include_all=include_all)


async def get_instructor_fces(
    instructor: str, include_all: bool = False
) -> FCESummary:
    """Fetch Faculty Course Evaluations (FCE) ratings for an instructor.

    Use this for a professor's teaching record across courses or to
    compare instructors. Returns a compact summary by default.

    **Auth required.** Same `SCOTTYLABS_AUTH_TOKEN` requirement as
    `get_course_fces`.

    Args:
        instructor: Instructor name *exactly* as it appears in the course
            data — pass values from `search_instructors` verbatim.
        include_all: See `get_course_fces`. Default `False` returns the
            5 most recent rows; aggregates always cover everything.

    Returns:
        `FCESummary` (see `get_course_fces`).

    Raises:
        ScottyLabsError: Network failure, 401, or other upstream error.
        ValueError: `instructor` is empty.
    """

    instructor = _require_nonempty(instructor, "instructor")
    fces = await _post_fces([("instructor", instructor)])
    return _summarize_fces(fces, include_all=include_all)


__all__ = [
    "GENED_SCHOOLS",
    "search_courses",
    "get_course",
    "get_course_schedules",
    "get_instructor_schedules",
    "get_requisites",
    "get_geneds",
    "search_instructors",
    "get_course_fces",
    "get_instructor_fces",
    "ScottyLabsError",
]
