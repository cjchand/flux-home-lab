"""FastAPI app: weekly tagging UI + health probe."""
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from drivelog import db, service
from drivelog.config import Settings

BASE = Path(__file__).parent
app = FastAPI(title="Drive Log")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

_settings: Settings | None = None
_bootstrapped = False


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def get_conn(settings: Settings = Depends(get_settings)):
    """One connection per request; rolled back on error, always closed."""
    global _bootstrapped
    conn = db.connect(settings)
    try:
        if not _bootstrapped:
            db.bootstrap(conn, student_name=settings.student_name)
            _bootstrapped = True
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fmt_min(m: int) -> str:
    h, mm = divmod(int(m), 60)
    if h and mm:
        return f"{h} h {mm:02d} m"
    return f"{h} h" if h else f"{mm} m"


def fmt_hours(m: int) -> str:
    return f"{m / 60:.1f}"


templates.env.filters["dur"] = fmt_min
templates.env.filters["hours"] = fmt_hours


def _parse_week(week: str | None) -> date:
    try:
        d = date.fromisoformat(week) if week else date.today()
    except ValueError:
        d = date.today()
    return service.week_sunday(d)


def _car(car: str | None) -> int | None:
    return int(car) if car and car.isdigit() else None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index(request: Request, week: str | None = None, car: str | None = None,
          driver: str = "all", conn=Depends(get_conn),
          settings: Settings = Depends(get_settings)):
    if driver not in ("all", "student", "me", "none"):
        driver = "all"
    ws = _parse_week(week)
    view = service.week_view(conn, settings, ws, _car(car), driver)
    return templates.TemplateResponse(request, "index.html", {
        "v": view,
        "prev_week": ws - timedelta(days=7),
        "next_week": ws + timedelta(days=7),
        "this_week": service.week_sunday(date.today()),
        "driver": driver,
        "car": view.car_id,
    })


@app.post("/tag")
def tag(drive_id: int = Form(...), driver: str = Form(...), week: str = Form(""),
        car: str = Form(""), view_driver: str = Form("all"), conn=Depends(get_conn)):
    if driver not in ("student", "me", "none"):
        return JSONResponse({"error": "bad driver"}, status_code=422)
    ids = service.get_driver_ids(conn)
    try:
        db.set_tag(conn, drive_id, ids.get(driver))
    except Exception:
        conn.rollback()
        raise
    qs = f"week={week}&driver={view_driver}" + (f"&car={car}" if car else "")
    return RedirectResponse(f"/?{qs}", status_code=303)
