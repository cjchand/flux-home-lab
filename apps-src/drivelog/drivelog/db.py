"""PostgreSQL data layer.

Reads Teslamate's ``public`` tables (SELECT only) and reads/writes tags in the
app-owned ``drivelog`` schema.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from typing import Iterable

import psycopg

from drivelog.config import Settings


@dataclass
class DriveRow:
    id: int
    start_utc: datetime
    end_utc: datetime
    duration_min: int | None
    car_id: int | None
    car_name: str | None
    start_lat: float | None
    start_lon: float | None
    start_label: str
    end_label: str
    driver_id: int | None


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


def bootstrap(conn: psycopg.Connection, student_name: str = "Toby") -> None:
    """Create the drivelog schema/tables and seed drivers. Idempotent."""
    sql = resources.files("drivelog").joinpath("sql/bootstrap.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "INSERT INTO drivelog.drivers (name, is_student) VALUES (%s, true) "
            "ON CONFLICT (name) DO NOTHING",
            (student_name,),
        )
        cur.execute(
            "INSERT INTO drivelog.drivers (name, is_student) VALUES ('me', false) "
            "ON CONFLICT (name) DO NOTHING"
        )
    conn.commit()


def _naive_utc(dt: datetime) -> datetime:
    # Teslamate stores naive UTC timestamps.
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


_FETCH_SQL = """
SELECT d.id,
       d.start_date,
       d.end_date,
       d.duration_min,
       d.car_id,
       c.name,
       sp.latitude::float8,
       sp.longitude::float8,
       COALESCE(sg.name, sa.display_name, sa.name, sa.city,
                CASE WHEN sp.id IS NOT NULL
                     THEN sp.latitude::text || ', ' || sp.longitude::text END,
                'Unknown') AS start_label,
       COALESCE(eg.name, ea.display_name, ea.name, ea.city,
                CASE WHEN ep.id IS NOT NULL
                     THEN ep.latitude::text || ', ' || ep.longitude::text END,
                'Unknown') AS end_label,
       t.driver_id
FROM public.drives d
LEFT JOIN public.cars c ON c.id = d.car_id
LEFT JOIN public.positions sp ON sp.id = d.start_position_id
LEFT JOIN public.positions ep ON ep.id = d.end_position_id
LEFT JOIN public.geofences sg ON sg.id = d.start_geofence_id
LEFT JOIN public.geofences eg ON eg.id = d.end_geofence_id
LEFT JOIN public.addresses sa ON sa.id = d.start_address_id
LEFT JOIN public.addresses ea ON ea.id = d.end_address_id
LEFT JOIN drivelog.drive_tags t ON t.teslamate_drive_id = d.id
WHERE d.end_date IS NOT NULL
  AND d.start_date >= %(start)s
  AND d.start_date < %(end)s
  AND (%(car_id)s::int IS NULL OR d.car_id = %(car_id)s::int)
ORDER BY d.start_date, d.id
"""


def fetch_drives(
    conn: psycopg.Connection,
    start_utc: datetime,
    end_utc: datetime,
    car_id: int | None,
) -> list[DriveRow]:
    params = {"start": _naive_utc(start_utc), "end": _naive_utc(end_utc), "car_id": car_id}
    with conn.cursor() as cur:
        cur.execute(_FETCH_SQL, params)
        rows = cur.fetchall()
    conn.commit()  # end the read transaction; don't hold it open
    return [DriveRow(*r) for r in rows]


def list_cars(conn: psycopg.Connection) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, COALESCE(name, 'Car ' || id) FROM public.cars ORDER BY id")
        rows = cur.fetchall()
    conn.commit()
    return [(int(i), n) for i, n in rows]


def set_tag(conn: psycopg.Connection, drive_id: int, driver_id: int | None) -> None:
    with conn.cursor() as cur:
        if driver_id is None:
            cur.execute(
                "DELETE FROM drivelog.drive_tags WHERE teslamate_drive_id = %s",
                (drive_id,),
            )
        else:
            cur.execute(
                "INSERT INTO drivelog.drive_tags (teslamate_drive_id, driver_id) "
                "VALUES (%s, %s) ON CONFLICT (teslamate_drive_id) "
                "DO UPDATE SET driver_id = EXCLUDED.driver_id, tagged_at = now()",
                (drive_id, driver_id),
            )
    conn.commit()


def get_tags(conn: psycopg.Connection, drive_ids: Iterable[int]) -> dict[int, int]:
    ids = list(drive_ids)
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT teslamate_drive_id, driver_id FROM drivelog.drive_tags "
            "WHERE teslamate_drive_id = ANY(%s) AND driver_id IS NOT NULL",
            (ids,),
        )
        rows = cur.fetchall()
    conn.commit()
    return {int(d): int(v) for d, v in rows}
