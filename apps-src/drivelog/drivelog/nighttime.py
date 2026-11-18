"""Texas night = sunset + 30 min -> sunrise - 30 min at the drive's location."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

BUFFER = timedelta(minutes=30)


def night_edges(local_date: date, lat: float, lon: float, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return (dusk, dawn) for local_date as tz-aware datetimes.

    dusk = sunset + 30 min, dawn = sunrise - 30 min (same calendar date).
    """
    obs = LocationInfo(latitude=lat, longitude=lon).observer
    s = sun(obs, date=local_date, tzinfo=tz)
    return s["sunset"] + BUFFER, s["sunrise"] - BUFFER


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def split_day_night(start_utc: datetime, end_utc: datetime, lat: float, lon: float,
                    tz: ZoneInfo) -> tuple[int, int]:
    """Return (day_minutes, night_minutes) summing to the drive's whole-minute duration.

    Naive datetimes are treated as UTC. Each minute is classified by its midpoint:
    night if at/after that local date's dusk or at/before its dawn.
    """
    start, end = _as_utc(start_utc), _as_utc(end_utc)
    total = max(0, round((end - start).total_seconds() / 60))
    edges: dict[date, tuple[datetime, datetime]] = {}
    night = 0
    for i in range(total):
        mid = (start + timedelta(minutes=i, seconds=30)).astimezone(tz)
        d = mid.date()
        if d not in edges:
            edges[d] = night_edges(d, lat, lon, tz)
        dusk, dawn = edges[d]
        if mid >= dusk or mid <= dawn:
            night += 1
    return total - night, night
