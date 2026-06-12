"""Interval ladder math. Pure functions, day granularity, local time.

`rung` = number of completed revisions. interval(rung) is the gap in days
between the rung-th completion (or initial capture, for rung 0) and the next
revision: 1, 3, 7, 14, 30, 60, 120, then doubling forever.
"""
from datetime import date, timedelta

LADDER = [1, 3, 7, 14, 30, 60, 120]


def interval(rung: int) -> int:
    if rung < 0:
        raise ValueError(f"rung must be >= 0, got {rung}")
    if rung < len(LADDER):
        return LADDER[rung]
    return LADDER[-1] * 2 ** (rung - len(LADDER) + 1)


def first_due(learned_on: date) -> date:
    return learned_on + timedelta(days=interval(0))


def next_due_after_completion(new_rung: int, completed_on: date) -> date:
    return completed_on + timedelta(days=interval(new_rung))


def overdue_days(next_due: date, today: date) -> int:
    return max(0, (today - next_due).days)
