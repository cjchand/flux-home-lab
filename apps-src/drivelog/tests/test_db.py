"""Integration tests. Require a SCRATCH Postgres (never the live Teslamate DB):

    docker run --rm -d -e POSTGRES_PASSWORD=x -p 5433:5432 postgres:16
    DRIVELOG_TEST_DSN=postgresql://postgres:x@localhost:5433/postgres pytest -q

The fixture TRUNCATEs/recreates public.drives etc. and drops schema drivelog.
"""
import os
from datetime import datetime

import psycopg
import pytest

from drivelog import db

DSN = os.environ.get("DRIVELOG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DRIVELOG_TEST_DSN not set")

T0 = datetime(2026, 11, 1, 12, 0)
T1 = datetime(2026, 11, 2, 12, 0)

TESLAMATE_FIXTURE = """
CREATE TABLE IF NOT EXISTS public.cars (id smallint PRIMARY KEY, name text);
CREATE TABLE IF NOT EXISTS public.positions (id int PRIMARY KEY, latitude numeric, longitude numeric, date timestamp);
CREATE TABLE IF NOT EXISTS public.addresses (id int PRIMARY KEY, display_name text, name text, city text);
CREATE TABLE IF NOT EXISTS public.geofences (id int PRIMARY KEY, name text);
CREATE TABLE IF NOT EXISTS public.drives (
    id int PRIMARY KEY, start_date timestamp, end_date timestamp, duration_min smallint,
    distance double precision, car_id smallint, start_position_id int, end_position_id int,
    start_address_id int, end_address_id int, start_geofence_id int, end_geofence_id int);
TRUNCATE public.drives, public.positions, public.addresses, public.geofences, public.cars;
INSERT INTO public.cars VALUES (1, 'Sparky'), (2, 'Red Rocket');
INSERT INTO public.positions VALUES (10, 30.1, -97.7, NULL), (11, 30.2, -97.8, NULL);
INSERT INTO public.addresses VALUES (20, '1 Main St, Town', NULL, 'Town');
INSERT INTO public.geofences VALUES (30, 'Home');
-- 100: geofence start label, address end label
INSERT INTO public.drives (id,start_date,end_date,duration_min,car_id,start_position_id,end_position_id,start_address_id,end_address_id,start_geofence_id)
  VALUES (100, '2026-11-01 13:00', '2026-11-01 13:30', 30, 1, 10, 11, 20, 20, 30);
-- 101: in-progress
INSERT INTO public.drives (id,start_date,end_date,car_id,start_position_id) VALUES (101, '2026-11-01 14:00', NULL, 1, 10);
-- 102: other car, NULL start position, no address/geofence
INSERT INTO public.drives (id,start_date,end_date,duration_min,car_id)
  VALUES (102, '2026-11-01 15:00', '2026-11-01 15:20', 20, 2);
-- 103: out of range
INSERT INTO public.drives (id,start_date,end_date,duration_min,car_id)
  VALUES (103, '2026-12-01 15:00', '2026-12-01 15:20', 20, 1);
"""


@pytest.fixture
def conn():
    c = psycopg.connect(DSN)
    with c.cursor() as cur:
        cur.execute(TESLAMATE_FIXTURE)
        cur.execute("DROP SCHEMA IF EXISTS drivelog CASCADE")
    c.commit()
    db.bootstrap(c, "Toby")
    yield c
    c.rollback()
    c.close()


def _driver_id(conn, name):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM drivelog.drivers WHERE name=%s", (name,))
        return cur.fetchone()[0]


def test_bootstrap_idempotent(conn):
    db.bootstrap(conn, "Toby")
    db.bootstrap(conn, "Toby")
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='drivelog'")
        assert {r[0] for r in cur.fetchall()} >= {"drivers", "drive_tags", "settings"}
        cur.execute("SELECT name, is_student FROM drivelog.drivers")
        assert set(cur.fetchall()) == {("Toby", True), ("me", False)}


def test_tag_roundtrip(conn):
    me, toby = _driver_id(conn, "me"), _driver_id(conn, "Toby")
    db.set_tag(conn, 100, me)
    assert db.get_tags(conn, [100, 102]) == {100: me}
    db.set_tag(conn, 100, toby)  # upsert
    assert db.get_tags(conn, [100]) == {100: toby}
    assert [d.driver_id for d in db.fetch_drives(conn, T0, T1, 1)] == [toby]
    db.set_tag(conn, 100, None)
    assert db.get_tags(conn, [100]) == {}
    assert db.get_tags(conn, []) == {}


def test_fetch_excludes_in_progress(conn):
    ids = [d.id for d in db.fetch_drives(conn, T0, T1, None)]
    assert 101 not in ids
    assert ids == [100, 102]  # 103 is out of range


def test_fetch_car_filter(conn):
    assert [d.id for d in db.fetch_drives(conn, T0, T1, 1)] == [100]
    assert [d.id for d in db.fetch_drives(conn, T0, T1, 2)] == [102]
    assert db.list_cars(conn) == [(1, "Sparky"), (2, "Red Rocket")]


def test_fetch_labels_and_positions(conn):
    d100, d102 = db.fetch_drives(conn, T0, T1, None)
    assert d100.start_label == "Home"
    assert d100.end_label == "1 Main St, Town"
    assert (d100.start_lat, d100.start_lon) == (30.1, -97.7)
    assert d100.car_name == "Sparky" and d100.duration_min == 30
    assert d102.start_lat is None and d102.start_lon is None
    assert d102.start_label == "Unknown"
