from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from drivelog import app as appmod, db, service
from drivelog.config import Settings

SETTINGS = Settings("h", 5432, "d", "u", "p", ZoneInfo("America/Chicago"), "Toby",
                    30, 10, 30.27, -97.74)


def drive(id, start, end, driver_id=None, lat=30.27):
    return db.DriveRow(id, start, end, int((end - start).total_seconds() // 60), 1, "Sparky",
                       lat, -97.74, "Home", "Costco", driver_id)


# 10:00-11:30 local (CST = UTC-6) -> 16:00-17:30 UTC, daytime, 90 min, tagged student (id 7)
D1 = drive(1, datetime(2026, 11, 11, 16, 0), datetime(2026, 11, 11, 17, 30), driver_id=7)
# untagged, NULL coords -> home fallback
D2 = drive(2, datetime(2026, 11, 12, 16, 0), datetime(2026, 11, 12, 16, 20), lat=None)


# lifetime student drives (start, end, lat, lon): includes one in an earlier week (2 h -> 1 h cap)
LIFETIME = [
    (D1.start_utc, D1.end_utc, 30.27, -97.74),
    (datetime(2026, 10, 20, 16, 0), datetime(2026, 10, 20, 18, 0), 30.27, -97.74),
]


class FakeConn:
    def rollback(self): pass
    def commit(self): pass


@pytest.fixture
def client(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "fetch_drives", lambda c, s, e, car: [D1, D2])
    monkeypatch.setattr(service, "fetch_student_drives", lambda c, sid: LIFETIME)
    monkeypatch.setattr(db, "list_cars", lambda c: [(1, "Sparky")])
    monkeypatch.setattr(db, "set_tag", lambda c, d, v: calls.append((d, v)))
    monkeypatch.setattr(service, "get_driver_ids",
                        lambda c: {"none": None, "student": 7, "me": 8})
    appmod.app.dependency_overrides[appmod.get_conn] = lambda: FakeConn()
    appmod.app.dependency_overrides[appmod.get_settings] = lambda: SETTINGS
    c = TestClient(appmod.app, follow_redirects=False)
    c.calls = calls
    yield c
    appmod.app.dependency_overrides.clear()


def test_healthz_ok():
    # no dependency overrides: must not touch the DB or env settings
    assert TestClient(appmod.app).get("/healthz").json() == {"status": "ok"}


def test_index_renders_week(client):
    r = client.get("/?week=2026-11-08")
    assert r.status_code == 200
    assert 'data-drive="1"' in r.text and 'data-drive="2"' in r.text
    # cards are cumulative: 90 min (capped 1 h) this week + 2 h (capped 1 h) in Oct = 2.0 h, 2 days
    total_card = r.text.split('id="card-total"')[1].split("</div>")[1]
    assert '<span class="val">2.0</span>' in total_card
    assert 'Home &rarr; Costco' in r.text
    assert "Home &rarr; Costco" in r.text


def test_tag_persists_and_redirects(client):
    r = client.post("/tag", data={"drive_id": "2", "driver": "student",
                                  "week": "2026-11-08", "car": "", "view_driver": "all"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/?week=2026-11-08")
    assert client.calls == [(2, 7)]
    client.post("/tag", data={"drive_id": "2", "driver": "none", "week": "2026-11-08"})
    assert client.calls[-1] == (2, None)


def test_untagged_filter(client):
    r = client.get("/?week=2026-11-08&driver=none")
    assert 'data-drive="2"' in r.text and 'data-drive="1"' not in r.text


def test_cards_are_cumulative_across_weeks(client):
    # viewing a week with no drives at all: lifetime (1 h + 1 h capped) still shows
    r = client.get("/?week=2026-11-22")
    total_card = r.text.split('id="card-total"')[1].split("</div>")[1]
    assert '<span class="val">2.0</span>' in total_card
    assert '<span class="val">2</span>' in r.text.split('id="card-days"')[1]


def test_missing_driver_rows_fail_loudly():
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a): pass
        def fetchall(self): return [(7, "Toby", True)]  # no "me"

    class C(FakeConn):
        def cursor(self): return Cur()

    with pytest.raises(LookupError):
        service.get_driver_ids(C())


def test_null_coords_use_home_fallback(monkeypatch):
    # 20:00-21:00 CST Nov 12 = after dusk at home -> all night
    d3 = drive(3, datetime(2026, 11, 13, 2, 0), datetime(2026, 11, 13, 3, 0), driver_id=7, lat=None)
    monkeypatch.setattr(db, "fetch_drives", lambda c, s, e, car: [d3])
    monkeypatch.setattr(db, "list_cars", lambda c: [])
    monkeypatch.setattr(service, "fetch_student_drives", lambda c, sid: [])
    monkeypatch.setattr(service, "get_driver_ids", lambda c: {"none": None, "student": 7, "me": 8})
    from datetime import date
    v = service.week_view(FakeConn(), SETTINGS, date(2026, 11, 8), None)
    x = v.days[0].drives[0]
    assert (x.day_min, x.night_min) == (0, 60)


def test_redirect_is_urlencoded(client):
    r = client.post("/tag", data={"drive_id": "1", "driver": "me", "week": "2026-11-08",
                                  "car": "1&x=2", "view_driver": "all"})
    assert "car=1%262" in r.headers["location"] or "car=1%26x%3D2" in r.headers["location"]
