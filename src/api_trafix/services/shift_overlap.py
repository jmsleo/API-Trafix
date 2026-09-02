"""Overlap detection for work shifts.

Shifts are modelled as half-open time ranges on a 24-hour clock (in minutes).
A ``crosses_midnight`` shift wraps around: its coverage is ``[start, 1440)``
plus ``[0, finish)``. Two shifts overlap when their covered minute ranges
intersect; a shift that merely touches another (finish == other.start) does NOT
overlap.
"""

from __future__ import annotations

from datetime import datetime, time

from api_trafix.models.shifts import Shift

MINUTES_PER_DAY = 24 * 60


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def shift_covers_datetime(
    dt: datetime, start: time, finish: time, crosses_midnight: bool
) -> bool:
    """Whether ``dt``'s clock time falls inside the shift's window."""
    minute = dt.hour * 60 + dt.minute
    return any(
        minute in covered
        for covered in shift_covers_minutes(start, finish, crosses_midnight)
    )


def shift_covers_minutes(
    start: time, finish: time, crosses_midnight: bool
) -> tuple[set[int], ...]:
    s = _to_minutes(start)
    f = _to_minutes(finish)
    if crosses_midnight:
        # [start, 24:00) U [00:00, finish)
        return (
            set(range(s, MINUTES_PER_DAY)),
            set(range(0, f)),
        )
    # [start, finish) with finish > start
    return (set(range(s, f)),)


def shift_covers_datetime(
    dt: datetime, start: time, finish: time, crosses_midnight: bool
) -> bool:
    """Whether ``dt``'s clock time falls inside the shift's window."""
    minute = dt.hour * 60 + dt.minute
    return any(
        minute in covered
        for covered in shift_covers_minutes(start, finish, crosses_midnight)
    )


def shifts_overlap(
    a_start: time,
    a_finish: time,
    a_crosses: bool,
    b_start: time,
    b_finish: time,
    b_crosses: bool,
) -> bool:
    a_ranges = shift_covers_minutes(a_start, a_finish, a_crosses)
    b_ranges = shift_covers_minutes(b_start, b_finish, b_crosses)
    for ar in a_ranges:
        for br in b_ranges:
            if not ar.isdisjoint(br):
                return True
    return False


def find_conflicting_shifts(
    candidate: Shift,
    others: list[Shift],
) -> list[Shift]:
    return [
        other
        for other in others
        if other.id != candidate.id
        and shifts_overlap(
            candidate.start_time,
            candidate.finish_time,
            candidate.crosses_midnight,
            other.start_time,
            other.finish_time,
            other.crosses_midnight,
        )
    ]
