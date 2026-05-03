"""Smoke-test the tool functions directly against the live ScottyLabs API.

Bypasses MCP transport — useful for quickly sanity-checking the wiring
without spinning up a client. Honors `SCOTTYLABS_API_BASE` and
`SCOTTYLABS_AUTH_TOKEN`.

Run:
    uv run --directory scottylabs-mcp python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from scottylabs_mcp import client, tools  # noqa: E402
from scottylabs_mcp.client import CourseNotFoundError, ScottyLabsError  # noqa: E402


def _truncate(text: str, n: int = 100) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "..."


# --- existing MVP cases ----------------------------------------------------

async def case_search_keyword() -> bool:
    print("[1] search_courses(query='machine learning')")
    try:
        result = await tools.search_courses(query="machine learning", page=1)
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      totalDocs={result.totalDocs}, page={result.page}, docs={len(result.docs)}")
    for course in result.docs[:3]:
        print(f"      - {course.courseID}  {course.name}  ({course.units} units)")
    return result.totalDocs > 0 and len(result.docs) > 0


async def case_search_department() -> bool:
    print("[2] search_courses(query='15-122')")
    try:
        result = await tools.search_courses(query="15-122", page=1)
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      totalDocs={result.totalDocs}, docs={len(result.docs)}")
    if result.docs:
        course = result.docs[0]
        print(f"      top hit: {course.courseID}  {course.name}")
    return len(result.docs) > 0


async def case_get_course_dashed() -> bool:
    print("[3] get_course('15-122')")
    try:
        course = await tools.get_course("15-122")
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    schedules = len(course.schedules) if course.schedules else 0
    print(f"      {course.courseID} - {course.name}")
    print(f"      department={course.department}  units={course.units}  schedules={schedules}")
    print(f"      desc: {_truncate(course.desc)}")
    print(f"      prereqs: {course.prereqs}")
    return course.courseID == "15-122"


async def case_get_course_missing() -> bool:
    print("[4] get_course('99-999')  (expecting CourseNotFoundError)")
    try:
        await tools.get_course("99-999")
    except CourseNotFoundError as e:
        print(f"      ok, raised CourseNotFoundError: {_truncate(str(e), 120)}")
        return True
    except ScottyLabsError as e:
        print(f"      tolerated: {e}")
        return True
    print("      FAIL: expected an error, got a course")
    return False


# --- new cases for FCE / schedule / requisite / gened / instructor ---------

async def case_course_schedules() -> bool:
    print("[5] get_course_schedules('15-122')")
    try:
        schedules = await tools.get_course_schedules("15-122")
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      schedules: {len(schedules)}")
    if schedules:
        s = schedules[0]
        print(f"      first: {s.courseID}  {s.semester} {s.year}  lectures={len(s.lectures)}  sections={len(s.sections)}")
    return len(schedules) >= 1


async def case_instructor_schedules(instructor: str) -> bool:
    print(f"[6] get_instructor_schedules({instructor!r})")
    try:
        schedules = await tools.get_instructor_schedules(instructor)
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      schedules: {len(schedules)}")
    seen_courses = sorted({s.courseID for s in schedules})[:5]
    if seen_courses:
        print(f"      sample courseIDs: {seen_courses}")
    return len(schedules) >= 1


async def case_requisites_present() -> bool:
    print("[7] get_requisites('15-213')")
    try:
        req = await tools.get_requisites("15-213")
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      prereqs: {req.prereqs}")
    print(f"      prereqRelations: {req.prereqRelations}")
    print(f"      postreqs: {len(req.postreqs)} courses (sample {req.postreqs[:3]})")
    return len(req.prereqs) >= 1 and len(req.postreqs) >= 1


async def case_requisites_missing() -> bool:
    print("[8] get_requisites('99-999')  (expecting CourseNotFoundError)")
    try:
        await tools.get_requisites("99-999")
    except CourseNotFoundError as e:
        print(f"      ok, raised CourseNotFoundError: {_truncate(str(e), 120)}")
        return True
    except ScottyLabsError as e:
        print(f"      tolerated: {e}")
        return True
    print("      FAIL: expected an error, got data")
    return False


async def case_geneds_scs() -> bool:
    print("[9] get_geneds('SCS')")
    try:
        geneds = await tools.get_geneds("SCS")
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      geneds: {len(geneds)}")
    for g in geneds[:3]:
        print(f"      - {g.courseID}  tags={g.tags}  ({_truncate(g.name or '', 60)})")
    return len(geneds) >= 1


async def case_geneds_invalid_school() -> bool:
    print("[10] get_geneds('Bogus')  (expecting ValueError)")
    try:
        await tools.get_geneds("Bogus")  # type: ignore[arg-type]
    except ValueError as e:
        print(f"      ok, raised ValueError: {e}")
        return True
    print("      FAIL: expected ValueError")
    return False


async def case_search_instructors_unfiltered() -> tuple[bool, str | None]:
    print("[11] search_instructors()")
    try:
        names = await tools.search_instructors()
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return (False, None)
    print(f"      returned {len(names)} names (cap 50)")
    if names:
        print(f"      first 3: {names[:3]}")
    sample = names[0] if names else None
    return (1 <= len(names) <= 50, sample)


async def case_search_instructors_filtered() -> bool:
    print("[12] search_instructors(query='cervesato')")
    try:
        names = await tools.search_instructors(query="cervesato")
    except ScottyLabsError as e:
        print(f"      FAIL: {e}")
        return False
    print(f"      matches: {names}")
    return len(names) >= 1 and all("cervesato" in n.lower() for n in names)


async def case_course_fces() -> bool:
    """FCEs are auth-gated. Either path (success or 401) is acceptable —
    we report which one happened so the harness reveals prod's auth state."""
    print("[13] get_course_fces('15-122')")
    try:
        summary = await tools.get_course_fces("15-122")
    except ScottyLabsError as e:
        msg = str(e)
        if "SCOTTYLABS_AUTH_TOKEN" in msg or "401" in msg or "scottylabs-mcp-auth" in msg:
            print(f"      AUTH REQUIRED (prod has AUTH_ENABLED=true): {_truncate(msg, 140)}")
            return True
        print(f"      FAIL: {e}")
        return False
    print(
        f"      AUTH OPEN — entry_count={summary.entry_count} "
        f"avg_hrs_per_week={summary.avg_hrs_per_week} truncated={summary.truncated}"
    )
    print(f"      years_covered: {summary.years_covered[:5]}{'...' if len(summary.years_covered) > 5 else ''}")
    print(f"      avg_rating: {summary.avg_rating}")
    if summary.entries:
        f = summary.entries[0]
        print(f"      most recent: {f.courseID}  {f.semester} {f.year}  instructor={f.instructor}")
    return True


# --- runner -----------------------------------------------------------------

async def main() -> int:
    print(f"API base: {client.get_api_base()}")
    auth_set = bool(client.get_auth_token())
    print(f"SCOTTYLABS_AUTH_TOKEN set: {auth_set}\n")

    results: list[bool] = []

    for case in (
        case_search_keyword,
        case_search_department,
        case_get_course_dashed,
        case_get_course_missing,
        case_course_schedules,
    ):
        results.append(await case())
        print()

    ok_unfiltered, _ = await case_search_instructors_unfiltered()
    results.append(ok_unfiltered)
    print()

    # Use a stable, currently-teaching instructor — alphabetically-first
    # names tend to be retired/inactive and yield 0 schedules.
    results.append(await case_instructor_schedules("CERVESATO, ILIANO"))
    print()

    for case in (
        case_requisites_present,
        case_requisites_missing,
        case_geneds_scs,
        case_geneds_invalid_school,
        case_search_instructors_filtered,
        case_course_fces,
    ):
        results.append(await case())
        print()

    await client.aclose()

    passed = sum(results)
    total = len(results)
    print(f"Summary: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
