"""Behind-the-wheel totals with the Texas daily cap (pure functions)."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DayMinutes:
    local_date: date
    day_min: int
    night_min: int


@dataclass(frozen=True)
class Totals:
    counted_total_min: int
    counted_night_min: int
    raw_total_min: int
    raw_night_min: int
    days_logged: int


def cap_one_day(day_min: int, night_min: int, cap_min: int = 60) -> tuple[int, int]:
    """Cap one local day's minutes at cap_min, filling night first.

    Returns (counted_day, counted_night).
    """
    counted_night = min(night_min, cap_min)
    counted_day = min(day_min, cap_min - counted_night)
    return counted_day, counted_night


def summarize(days: list[DayMinutes], cap_min: int = 60) -> Totals:
    counted_total = counted_night = raw_total = raw_night = logged = 0
    for d in days:
        cd, cn = cap_one_day(d.day_min, d.night_min, cap_min)
        counted_total += cd + cn
        counted_night += cn
        raw_total += d.day_min + d.night_min
        raw_night += d.night_min
        if cd + cn > 0:
            logged += 1
    return Totals(counted_total, counted_night, raw_total, raw_night, logged)
