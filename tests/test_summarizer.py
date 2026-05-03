"""Offline tests for the FCE summarizer and ID normalization.

These run in CI — no network calls. The live-API smoke harness lives in
`scripts/smoke.py` and is intentionally not part of the test suite.
"""

from __future__ import annotations

import pytest

from scottylabs_mcp.models import FCE
from scottylabs_mcp.tools import (
    _avg_rating,
    _fce_sort_key,
    _normalize_course_id,
    _summarize_fces,
)


def _fce(year: int, semester: str, instructor: str, hrs: float, rating: list[float]) -> FCE:
    return FCE(
        courseID="15-122",
        year=str(year),
        semester=semester,
        instructor=instructor,
        hrsPerWeek=hrs,
        rating=rating,
    )


# --- _normalize_course_id ---------------------------------------------------


def test_normalize_inserts_dash() -> None:
    assert _normalize_course_id("15122") == "15-122"


def test_normalize_keeps_dashed() -> None:
    assert _normalize_course_id("15-122") == "15-122"


def test_normalize_strips_whitespace() -> None:
    assert _normalize_course_id("  21-241  ") == "21-241"


@pytest.mark.parametrize("bogus", ["", "abc", "1-2", "15-12", "151222", "15-1222"])
def test_normalize_rejects_garbage(bogus: str) -> None:
    with pytest.raises(ValueError):
        _normalize_course_id(bogus)


# --- _avg_rating ------------------------------------------------------------


def test_avg_rating_empty_returns_none() -> None:
    assert _avg_rating([]) is None


def test_avg_rating_all_empty_lists_returns_none() -> None:
    assert _avg_rating([[], []]) is None


def test_avg_rating_uniform() -> None:
    assert _avg_rating([[4.0, 3.0], [2.0, 5.0]]) == [3.0, 4.0]


def test_avg_rating_uneven_lengths() -> None:
    # Position 0 averages over both, position 1 only over the first.
    assert _avg_rating([[4.0, 3.0], [2.0]]) == [3.0, 3.0]


# --- _fce_sort_key ----------------------------------------------------------


def test_sort_key_orders_year_then_semester() -> None:
    items = [
        _fce(2024, "spring", "A", 10, [4.0]),
        _fce(2025, "fall", "B", 10, [4.0]),
        _fce(2024, "fall", "C", 10, [4.0]),
    ]
    items.sort(key=_fce_sort_key, reverse=True)
    assert [(_safe(i.year), i.semester) for i in items] == [
        (2025, "fall"),
        (2024, "fall"),
        (2024, "spring"),
    ]


def _safe(v: object) -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return 0


# --- _summarize_fces --------------------------------------------------------


def test_summarize_empty() -> None:
    s = _summarize_fces([], include_all=False)
    assert s.entry_count == 0
    assert s.years_covered == []
    assert s.avg_hrs_per_week is None
    assert s.avg_rating is None
    assert s.entries == []
    assert s.truncated is False


def test_summarize_truncates_to_five() -> None:
    fces = [_fce(2020 + i, "fall", "A", 10.0, [4.0]) for i in range(8)]
    s = _summarize_fces(fces, include_all=False)
    assert s.entry_count == 8
    assert len(s.entries) == 5
    assert s.truncated is True
    # Most recent first.
    assert str(s.entries[0].year) == "2027"


def test_summarize_include_all_returns_everything() -> None:
    fces = [_fce(2020 + i, "fall", "A", 10.0, [4.0]) for i in range(8)]
    s = _summarize_fces(fces, include_all=True)
    assert len(s.entries) == 8
    assert s.truncated is False


def test_summarize_aggregates() -> None:
    fces = [
        _fce(2024, "fall", "A", 10.0, [4.0, 4.5]),
        _fce(2023, "spring", "B", 12.0, [3.0, 3.5]),
        _fce(2022, "fall", "A", 8.0, [5.0, 4.0]),
    ]
    s = _summarize_fces(fces, include_all=False)
    assert s.entry_count == 3
    assert s.years_covered == [2024, 2023, 2022]  # sorted desc
    assert s.avg_hrs_per_week == 10.0  # mean of 10, 12, 8
    assert s.avg_rating == [4.0, 4.0]  # element-wise
    assert s.truncated is False


def test_summarize_skips_missing_hrs() -> None:
    fces = [
        FCE(courseID="15-122", year="2024", semester="fall", hrsPerWeek=10.0, rating=[]),
        FCE(courseID="15-122", year="2023", semester="fall", hrsPerWeek=None, rating=[]),
    ]
    s = _summarize_fces(fces, include_all=False)
    assert s.avg_hrs_per_week == 10.0
