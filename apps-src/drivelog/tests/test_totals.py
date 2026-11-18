from datetime import date

from drivelog.totals import DayMinutes, Totals, cap_one_day, summarize


def test_under_cap_unchanged():
    assert cap_one_day(30, 20) == (30, 20)


def test_over_cap_night_first():
    assert cap_one_day(40, 40) == (20, 40)


def test_over_cap_night_exceeds():
    assert cap_one_day(10, 80) == (0, 60)


def test_day_only_over_cap():
    assert cap_one_day(90, 0) == (60, 0)


def test_exactly_at_cap():
    assert cap_one_day(30, 30) == (30, 30)


def test_summarize_multiday():
    days = [
        DayMinutes(date(2026, 1, 1), 30, 20),  # under cap -> 30d/20n
        DayMinutes(date(2026, 1, 2), 40, 40),  # capped -> 20d/40n
        DayMinutes(date(2026, 1, 3), 10, 80),  # capped -> 0d/60n
    ]
    t = summarize(days)
    assert t == Totals(
        counted_total_min=170,
        counted_night_min=120,
        raw_total_min=220,
        raw_night_min=140,
        days_logged=3,
    )


def test_summarize_skips_zero_days_in_days_logged():
    t = summarize([DayMinutes(date(2026, 1, 1), 0, 0), DayMinutes(date(2026, 1, 2), 5, 0)])
    assert t.days_logged == 1
    assert t.counted_total_min == 5


def test_empty():
    assert summarize([]) == Totals(0, 0, 0, 0, 0)
