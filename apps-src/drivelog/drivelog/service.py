"""Glue: fetch drives -> day/night split -> tags -> capped totals."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from drivelog import db, nighttime, totals
from drivelog.config import Settings

CAP_MIN = 60


@dataclass
class DriveView:
    row: db.DriveRow
    local_start: datetime
    day_min: int
    night_min: int
    tag: str  # "student" | "me" | "none"
    counts_min: int = 0  # minutes this drive contributes after the daily cap

    @property
    def total_min(self) -> int:
        return self.day_min + self.night_min


@dataclass
class DayView:
    local_date: date
    drives: list[DriveView] = field(default_factory=list)
    counted_min: int = 0
    raw_min: int = 0  # student-tagged minutes before the cap


@dataclass
class WeekView:
    week_start: date
    week_end: date
    days: list[DayView]
    totals: totals.Totals  # cumulative (lifetime) -- feeds the progress cards
    week_totals: totals.Totals
    goal_total_min: int
    goal_night_min: int
    student_name: str
    cars: list[tuple[int, str]]
    driver_filter: str
    car_id: int | None

    @property
    def total_pct(self) -> int:
        return _pct(self.totals.counted_total_min, self.goal_total_min)

    @property
    def days_pct(self) -> int:
        return _pct(self.totals.days_logged * 60, self.goal_total_min)

    @property
    def night_pct(self) -> int:
        return _pct(self.totals.counted_night_min, self.goal_night_min)


def _pct(v: int, goal: int) -> int:
    return min(100, round(100 * v / goal)) if goal else 0


def week_sunday(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def get_driver_ids(conn) -> dict[str, int | None]:
    """Map UI choices to seeded driver ids: student -> is_student row, me -> 'me'."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, is_student FROM drivelog.drivers")
        rows = cur.fetchall()
    conn.commit()
    ids: dict[str, int | None] = {"none": None}
    for did, name, is_student in rows:
        if is_student:
            ids["student"] = did
        elif name == "me":
            ids["me"] = did
    missing = {"student", "me"} - ids.keys()
    if missing:
        raise LookupError(f"drivelog.drivers is missing seeded driver(s): {sorted(missing)}")
    return ids


_LIFETIME_SQL = """
SELECT d.start_date, d.end_date, sp.latitude::float8, sp.longitude::float8
FROM drivelog.drive_tags t
JOIN public.drives d ON d.id = t.teslamate_drive_id
LEFT JOIN public.positions sp ON sp.id = d.start_position_id
WHERE t.driver_id = %s AND d.end_date IS NOT NULL
"""


def fetch_student_drives(conn, student_id: int) -> list[tuple]:
    """All student-tagged drives (all cars, no date window): (start, end, lat, lon)."""
    with conn.cursor() as cur:
        cur.execute(_LIFETIME_SQL, (student_id,))
        rows = cur.fetchall()
    conn.commit()
    return rows


def _split(start, end, lat, lon, settings):
    lat = lat if lat is not None else settings.home_lat
    lon = lon if lon is not None else settings.home_lon
    return nighttime.split_day_night(start, end, lat, lon, settings.tz)


def lifetime_totals(conn, settings: Settings, student_id: int) -> totals.Totals:
    per_day: dict[date, list[int]] = {}
    for start, end, lat, lon in fetch_student_drives(conn, student_id):
        dm, nm = _split(start, end, lat, lon, settings)
        d = start.replace(tzinfo=timezone.utc).astimezone(settings.tz).date()
        acc = per_day.setdefault(d, [0, 0])
        acc[0] += dm
        acc[1] += nm
    return totals.summarize([totals.DayMinutes(d, a, b) for d, (a, b) in per_day.items()], CAP_MIN)


def week_view(conn, settings: Settings, week_start: date, car_id: int | None,
              driver_filter: str = "all") -> WeekView:
    tz = settings.tz
    start_local = datetime.combine(week_start, time.min, tzinfo=tz)
    end_local = datetime.combine(week_start + timedelta(days=7), time.min, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    try:
        rows = db.fetch_drives(conn, start_utc, end_utc, car_id)
        ids = get_driver_ids(conn)
        cars = db.list_cars(conn)
    except Exception:
        conn.rollback()
        raise
    tag_by_id = {v: k for k, v in ids.items() if v is not None}

    by_day: dict[date, DayView] = {}
    for r in rows:
        day_m, night_m = _split(r.start_utc, r.end_utc, r.start_lat, r.start_lon, settings)
        local_start = r.start_utc.replace(tzinfo=timezone.utc).astimezone(tz)
        dv = DriveView(r, local_start, day_m, night_m, tag_by_id.get(r.driver_id, "none"))
        by_day.setdefault(local_start.date(), DayView(local_start.date())).drives.append(dv)

    day_minutes = []
    for d in by_day.values():
        mine = [x for x in d.drives if x.tag == "student"]
        dm, nm = sum(x.day_min for x in mine), sum(x.night_min for x in mine)
        cd, cn = totals.cap_one_day(dm, nm, CAP_MIN)
        d.counted_min, d.raw_min = cd + cn, dm + nm
        remaining = d.counted_min
        for x in mine:  # allocate the capped minutes chronologically
            x.counts_min = min(x.total_min, remaining)
            remaining -= x.counts_min
        day_minutes.append(totals.DayMinutes(d.local_date, dm, nm))
    # Progress cards are cumulative over all cars/weeks; the table stays week-scoped.
    summary = lifetime_totals(conn, settings, ids["student"])
    week_summary = totals.summarize(day_minutes, CAP_MIN)

    days = sorted(by_day.values(), key=lambda d: d.local_date, reverse=True)
    if driver_filter in ("student", "me", "none"):
        for d in days:
            d.drives = [x for x in d.drives if x.tag == driver_filter]
        days = [d for d in days if d.drives]

    return WeekView(
        week_start=week_start, week_end=week_start + timedelta(days=6), days=days,
        totals=summary, week_totals=week_summary, goal_total_min=round(settings.goal_total_h * 60),
        goal_night_min=round(settings.goal_night_h * 60), student_name=settings.student_name,
        cars=cars, driver_filter=driver_filter, car_id=car_id,
    )
