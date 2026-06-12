from datetime import date

import pytest

from recallpro import scheduler


def test_ladder_values():
    assert [scheduler.interval(r) for r in range(7)] == [1, 3, 7, 14, 30, 60, 120]


def test_doubles_forever_after_ladder():
    assert scheduler.interval(7) == 240
    assert scheduler.interval(8) == 480
    assert scheduler.interval(10) == 1920


def test_negative_rung_rejected():
    with pytest.raises(ValueError):
        scheduler.interval(-1)


def test_first_due_is_next_day():
    assert scheduler.first_due(date(2026, 6, 12)) == date(2026, 6, 13)


def test_next_due_counts_from_completion_not_schedule():
    # due Jan 1, completed Jan 3 with new rung 1 (gap 3) → next due Jan 6
    assert scheduler.next_due_after_completion(1, date(2026, 1, 3)) == date(2026, 1, 6)


def test_overdue_days():
    assert scheduler.overdue_days(date(2026, 6, 10), date(2026, 6, 12)) == 2
    assert scheduler.overdue_days(date(2026, 6, 12), date(2026, 6, 12)) == 0
    assert scheduler.overdue_days(date(2026, 6, 14), date(2026, 6, 12)) == 0
