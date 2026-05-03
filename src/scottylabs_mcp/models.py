"""Pydantic models for the ScottyLabs API responses.

Mirrors `apps/frontend/src/app/types.ts` in the upstream repo. Fields are made
optional liberally — Mongo documents in the wild are messy and the upstream
TypeScript types lie about a few things.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Semester = Literal["fall", "spring", "summer", ""]


class Time(BaseModel):
    model_config = ConfigDict(extra="ignore")

    begin: str | None = None
    end: str | None = None
    days: list[int] = Field(default_factory=list)
    building: str | None = None
    room: str | None = None


class Lesson(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instructors: list[str] = Field(default_factory=list)
    name: str | None = None
    location: str | None = None
    times: list[Time] = Field(default_factory=list)


class Section(Lesson):
    lecture: str | None = None


class Schedule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    courseID: str
    year: str | int | None = None
    semester: Semester | str | None = None
    session: str | None = None
    lectures: list[Lesson] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    instructors: list[str] = Field(default_factory=list)


class FCE(BaseModel):
    model_config = ConfigDict(extra="ignore")

    courseID: str
    courseName: str | None = None
    department: str | None = None
    instructor: str | None = None
    year: str | int | None = None
    semester: Semester | str | None = None
    session: str | None = None
    college: str | None = None
    level: str | None = None
    hrsPerWeek: float | None = None
    numRespondents: int | None = None
    possibleRespondents: int | None = None
    rating: list[float] = Field(default_factory=list)
    responseRate: str | None = None
    andrewID: str | None = None
    location: str | None = None


class Course(BaseModel):
    model_config = ConfigDict(extra="ignore")

    courseID: str
    name: str
    department: str
    desc: str = ""
    units: str | None = None
    manualUnits: str | None = None
    prereqs: list[str] = Field(default_factory=list)
    prereqString: str = ""
    coreqs: list[str] = Field(default_factory=list)
    crosslisted: list[str] = Field(default_factory=list)
    schedules: list[Schedule] | None = None
    fces: list[FCE] | None = None


class CourseSearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    totalDocs: int
    totalPages: int
    page: int
    docs: list[Course]


class CourseRequisites(BaseModel):
    """Prereq/postreq graph for a single course.

    `prereqRelations` is an AND-of-ORs decoding of the upstream
    `prereqString` — outer list joined by AND, inner list joined by OR.
    """

    model_config = ConfigDict(extra="ignore")

    prereqs: list[str] = Field(default_factory=list)
    prereqRelations: list[list[str]] = Field(default_factory=list)
    postreqs: list[str] = Field(default_factory=list)


class FCESummary(BaseModel):
    """Aggregate view of FCE entries for a course or instructor.

    The default response from `get_course_fces` / `get_instructor_fces` —
    keeps payloads tight by collapsing dozens of per-semester rows into a
    handful of aggregates plus the 5 most recent entries. Pass
    `include_all=True` on the tool to populate `entries` with every row;
    `truncated` flags whether anything was cut.
    """

    model_config = ConfigDict(extra="ignore")

    entry_count: int
    years_covered: list[int] = Field(default_factory=list)
    avg_hrs_per_week: float | None = None
    avg_rating: list[float] | None = None
    entries: list[FCE] = Field(default_factory=list)
    truncated: bool = False


class Gened(BaseModel):
    """A course tagged as a gen-ed for some school.

    `fces` is populated only by the auth-gated POST variant; the public
    GET path leaves it empty.
    """

    model_config = ConfigDict(extra="ignore")

    courseID: str
    name: str | None = None
    units: str | None = None
    desc: str | None = None
    tags: list[str] = Field(default_factory=list)
    startsCounting: str | None = None
    stopsCounting: str | None = None
    fces: list[FCE] = Field(default_factory=list)
