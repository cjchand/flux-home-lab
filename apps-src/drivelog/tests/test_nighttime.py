from datetime import date, datetime
from zoneinfo import ZoneInfo

from drivelog.nighttime import night_edges, split_day_night

TZ = ZoneInfo("America/Chicago")
LAT, LON = 30.27, -97.74


def local(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_night_edges_order_and_tz():
    dusk, dawn = night_edges(date(2026, 6, 15), LAT, LON, TZ)
    assert dusk.tzinfo is not None and dawn.tzinfo is not None
    assert dawn.hour in (5, 6) and dusk.hour in (20, 21)


def test_all_daytime_drive():
    assert split_day_night(local(2026, 6, 15, 13, 0), local(2026, 6, 15, 13, 40), LAT, LON, TZ) == (40, 0)


def test_all_nighttime_drive():
    assert split_day_night(local(2026, 6, 15, 22, 0), local(2026, 6, 15, 22, 50), LAT, LON, TZ) == (0, 50)


def test_crosses_dusk():
    dusk, _ = night_edges(date(2026, 6, 15), LAT, LON, TZ)
    start = dusk.replace(second=0, microsecond=0) - __import__("datetime").timedelta(minutes=20)
    end = start + __import__("datetime").timedelta(minutes=60)
    day, night = split_day_night(start, end, LAT, LON, TZ)
    assert day + night == 60
    assert night > 0 and day > 0
    assert abs(day - 20) <= 1


def test_midnight_spanning():
    assert split_day_night(local(2026, 6, 15, 23, 30), local(2026, 6, 16, 0, 30), LAT, LON, TZ) == (0, 60)


def test_naive_input_treated_as_utc():
    # 18:00-18:40 UTC in June = 13:00-13:40 CDT
    assert split_day_night(datetime(2026, 6, 15, 18, 0), datetime(2026, 6, 15, 18, 40), LAT, LON, TZ) == (40, 0)


def test_null_gps_uses_home_fallback():
    # Fallback to home coords happens in the DB layer; here any coords work.
    day, night = split_day_night(local(2026, 6, 15, 13, 0), local(2026, 6, 15, 13, 30), 45.0, -100.0, TZ)
    assert (day, night) == (30, 0)


def test_dst_transition_date():
    # 2026-03-08 spring forward in US; 01:30 CST -> 03:30 CDT is 60 real minutes, all night.
    start = datetime(2026, 3, 8, 7, 30)  # naive UTC = 01:30 CST
    end = datetime(2026, 3, 8, 8, 30)    # 03:30 CDT
    day, night = split_day_night(start, end, LAT, LON, TZ)
    assert day + night == 60
    assert (day, night) == (0, 60)


def test_dst_daytime_drive_sums():
    start = datetime(2026, 3, 8, 18, 0)
    end = datetime(2026, 3, 8, 18, 45)
    assert split_day_night(start, end, LAT, LON, TZ) == (45, 0)
