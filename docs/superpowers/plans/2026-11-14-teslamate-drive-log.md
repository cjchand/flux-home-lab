# Teslamate Drive Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small internal web app that lists the Tesla's drives by week, lets the owner tag which ones Toby drove, and reports Texas-correct day/night totals toward the 30 h / 10 night behind-the-wheel requirement.

**Architecture:** Single Python container (FastAPI + server-rendered Jinja templates + light vanilla JS). Correctness-critical logic (day/night split, daily cap) lives in pure, unit-tested functions with no DB. A thin psycopg3 data layer reads Teslamate's `public` tables read-only and reads/writes tags in a new `drivelog` schema in the same database. Deployed via plain k8s manifests reconciled by Flux, image built by GitHub Actions.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, psycopg3, astral (sunrise/sunset), pytest. Deployed on microk8s in the `teslamate` namespace; image `ghcr.io/cjchand/drivelog`.

**Spec:** `docs/superpowers/specs/2026-11-13-teslamate-drive-log-design.md`

## Global Constraints

- Python **3.12**; dependencies limited to: fastapi, uvicorn, jinja2, psycopg[binary] (v3), astral, pytest (dev). No SPA framework, no ORM.
- The app **only writes to the `drivelog` schema**; all access to Teslamate's `public` tables is **read-only** (SELECT).
- DB connection uses the existing **`teslamate-postgres`** secret, key **`teslamate_user_pass`**, username **`teslamate`**, database **`teslamate`**, host **`teslamate-pg-rw`**, port **5432** (verified: this user has CREATE on the DB).
- Teslamate timestamps are **naive UTC**; treat as UTC, display/aggregate in **`America/Chicago`** (configurable via `DRIVELOG_TZ`).
- Texas night = **sunset + 30 min → sunrise − 30 min**, computed per drive via sunrise/sunset at the drive's start location.
- Daily cap = **60 counted minutes per local calendar day**, filled **night-minutes-first** then day; the 10 h night sub-total is computed from the **capped** minutes.
- Student name default **"Toby"** (`DRIVELOG_STUDENT_NAME`); goal defaults **30 h total / 10 h night** (`DRIVELOG_GOAL_TOTAL_H`, `DRIVELOG_GOAL_NIGHT_H`).
- Deployed as a plain **Deployment/Service/Ingress** (NOT a HelmRelease), namespace **`teslamate`**; ingress via Traefik with `cert-manager.io/cluster-issuer: internal-ca`, host **`drivelog.internal`**, plus `gethomepage.dev/*` annotations like the other apps.
- No authentication (internal network only).

## Review Focus

- **Drive with NULL `start_position_id`** (no GPS fix): day/night must fall back to the configured home lat/lng, not crash. → test in Task 1.
- **In-progress drive (`end_date` IS NULL)**: must be excluded from the list/totals, not treated as zero-length or crash. → test in Task 3.
- **Midnight-spanning drive**: minutes must be attributed to the correct *local* calendar day for the 60-min cap (each side counts under its own date). → test in Task 2.
- **Two cars**: tagging and totals must not mix cars incorrectly; each drive's car is shown and totals are over all tagged-as-Toby drives regardless of car, with an optional car filter on the list. → test in Task 3/Task 4.
- **DST transition date**: sunrise/sunset and the day boundary must use the zone's actual offset that day (astral with a tz-aware date handles this). → test in Task 1.

---

### Task 1: Project scaffold + config + day/night computation

**Files:**
- Create: `apps-src/drivelog/pyproject.toml` (deps, python 3.12)
- Create: `apps-src/drivelog/drivelog/__init__.py`
- Create: `apps-src/drivelog/drivelog/config.py`
- Create: `apps-src/drivelog/drivelog/nighttime.py`
- Test: `apps-src/drivelog/tests/test_nighttime.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `config.Settings` (pydantic-free dataclass) read from env: `db_host, db_port, db_name, db_user, db_password, tz` (ZoneInfo name), `student_name`, `goal_total_h`, `goal_night_h`, `home_lat`, `home_lon`. Classmethod `Settings.from_env() -> Settings`.
  - `nighttime.split_day_night(start_utc: datetime, end_utc: datetime, lat: float, lon: float, tz: ZoneInfo) -> tuple[int, int]` → `(day_minutes, night_minutes)`, rounded to whole minutes, summing to the drive's duration.
  - `nighttime.night_edges(local_date: date, lat: float, lon: float, tz: ZoneInfo) -> tuple[datetime, datetime]` → `(dusk, dawn)` = `(sunset+30min, sunrise-30min)` as tz-aware datetimes.

- [ ] **Step 1: Write failing tests** in `tests/test_nighttime.py`:
  - `test_all_daytime_drive` — a drive fully between dawn and dusk (e.g. 2026-06-15 13:00–13:40 local, Austin TX lat 30.27, lon -97.74) → `(40, 0)`.
  - `test_all_nighttime_drive` — 22:00–22:50 local same location → `(0, 50)`.
  - `test_crosses_dusk` — starts before sunset+30, ends after; split minutes sum to duration and night portion > 0.
  - `test_midnight_spanning` — 23:30–00:30 local → both minutes are night, total 60.
  - `test_null_gps_uses_home_fallback` — caller passes home lat/lon; function still returns a valid split (document: fallback happens in the DB layer; here just assert it works for arbitrary coords).
  - `test_dst_transition_date` — a drive on the US spring-forward date returns a split consistent with that day's offset (no exception, minutes sum to duration).
- [ ] **Step 2: Run tests, verify they fail** — `pytest apps-src/drivelog/tests/test_nighttime.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `config.py` and `nighttime.py`.** Approach for `split_day_night`: convert start/end to `tz`; for each local calendar date the drive touches, compute `night_edges`; walk the drive interval minute-ranges, classifying each sub-interval as night if it lies at/after that date's dusk or at/before that date's dawn, else day; sum. Use `astral.sun.sun()` for sunrise/sunset.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(drivelog): day/night split + config scaffold`.

### Task 2: Totals with Texas daily cap

**Files:**
- Create: `apps-src/drivelog/drivelog/totals.py`
- Test: `apps-src/drivelog/tests/test_totals.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - A `DayMinutes` dataclass `(local_date: date, day_min: int, night_min: int)`.
  - `totals.summarize(days: list[DayMinutes], cap_min: int = 60) -> Totals` where `Totals` has `counted_total_min, counted_night_min, raw_total_min, raw_night_min, days_logged`.
  - `totals.cap_one_day(day_min: int, night_min: int, cap_min: int = 60) -> tuple[int, int]` → `(counted_day, counted_night)` filling night first.

- [ ] **Step 1: Write failing tests** in `tests/test_totals.py`:
  - `test_under_cap_unchanged` — (30 day, 20 night) → counted (30, 20).
  - `test_over_cap_night_first` — (40 day, 40 night) → counted (20 day, 40 night) i.e. night fills first to 40, day gets remaining 20.
  - `test_over_cap_night_exceeds` — (10 day, 80 night) → (0 day, 60 night).
  - `test_day_only_over_cap` — (90 day, 0 night) → (60, 0).
  - `test_summarize_multiday` — three days, verify `counted_total_min`, `counted_night_min` (from capped minutes), `raw_*`, and `days_logged == 3`.
  - `test_empty` — `[]` → all zeros, days_logged 0.
- [ ] **Step 2: Run tests, verify fail.**
- [ ] **Step 3: Implement `totals.py`** per the Global Constraints cap rule.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(drivelog): daily-cap totals (night-first)`.

### Task 3: Data layer — schema bootstrap, drive queries, tags

**Files:**
- Create: `apps-src/drivelog/drivelog/db.py`
- Create: `apps-src/drivelog/drivelog/sql/bootstrap.sql`
- Test: `apps-src/drivelog/tests/test_db.py` (integration; skipped unless `DRIVELOG_TEST_DSN` is set)

**Interfaces:**
- Consumes: `config.Settings`.
- Produces:
  - `db.bootstrap(conn)` — idempotent: `CREATE SCHEMA IF NOT EXISTS drivelog`; create `drivelog.drivers(id serial pk, name text unique, is_student bool)`, `drivelog.drive_tags(teslamate_drive_id bigint primary key, driver_id int references drivelog.drivers(id), tagged_at timestamptz default now())`, `drivelog.settings(key text pk, value text)`; seed a student row from `settings.student_name` and a `"me"` driver.
  - `db.fetch_drives(conn, start_utc, end_utc, car_id: int | None) -> list[DriveRow]` where `DriveRow` = `(id, start_utc, end_utc, duration_min, car_id, car_name, start_lat, start_lon, start_label, end_label, driver_id|None)`. Joins `drives` → `positions` (start), `geofences`/`addresses` for labels (prefer geofence name, else address `display_name`/`city`, else lat/lon), `cars` for name. **Excludes rows where `end_date IS NULL`.** Null `start_position_id` → lat/lon returned as NULL (caller substitutes home).
  - `db.list_cars(conn) -> list[tuple[int,str]]`.
  - `db.set_tag(conn, drive_id: int, driver_id: int | None)` — upsert; `None` deletes the tag (untag).
  - `db.get_tags(conn, drive_ids) -> dict[int,int]`.

- [ ] **Step 1: Write failing integration tests** (`pytest.mark.skipif` no `DRIVELOG_TEST_DSN`): `test_bootstrap_idempotent` (run twice, no error, tables exist), `test_tag_roundtrip` (set tag → get_tags returns it → untag removes it), `test_fetch_excludes_in_progress` (insert a fixture drive with NULL end_date into a temp fixture, assert excluded), `test_fetch_car_filter`.
- [ ] **Step 2: Run tests — fail** (module missing) or skip if no DSN; set `DRIVELOG_TEST_DSN` to a throwaway Postgres (document: `kubectl port-forward` to the teslamate PG into a scratch DB, or a local container) and confirm fail.
- [ ] **Step 3: Implement `db.py` + `bootstrap.sql`.** Use a psycopg3 connection pool. All Teslamate-table access is SELECT only.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(drivelog): postgres data layer + drivelog schema`.

### Task 4: Web app — weekly view, tagging, health

**Files:**
- Create: `apps-src/drivelog/drivelog/app.py`
- Create: `apps-src/drivelog/drivelog/templates/index.html`
- Create: `apps-src/drivelog/drivelog/static/app.js`
- Create: `apps-src/drivelog/drivelog/service.py` (glue: fetch drives → split day/night → attach tags → summarize)
- Test: `apps-src/drivelog/tests/test_app.py` (FastAPI `TestClient`, db layer faked)

**Interfaces:**
- Consumes: `config`, `db`, `nighttime`, `totals`.
- Produces:
  - `service.week_view(conn, settings, week_start: date, car_id) -> WeekView` (drives grouped by local day with per-drive split, per-day counted, and `Totals`). For NULL lat/lon, substitute `settings.home_lat/lon`.
  - FastAPI routes: `GET /` (optional `?week=YYYY-MM-DD&car=<id>&driver=<filter>`, default current week, Sunday-start), `POST /tag` (form: `drive_id`, `driver` ∈ {student, me, none}) → redirect back to same week, `GET /healthz` → `{"status":"ok"}`.

- [ ] **Step 1: Write failing tests** in `tests/test_app.py`: `test_healthz_ok`; `test_index_renders_week` (fake db returns 2 drives; assert both appear and the totals card reflects the capped sum); `test_tag_persists_and_redirects` (POST /tag calls `db.set_tag` with mapped driver_id and 303s back); `test_untagged_filter` (driver=none shows only untagged).
- [ ] **Step 2: Run tests — fail.**
- [ ] **Step 3: Implement `service.py`, `app.py`, templates, `app.js`** (checkbox posts to `/tag`; week nav links; three progress cards; day-grouped table matching the approved mockup — day/night pills, capped "counts" column, route labels, car name).
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(drivelog): weekly tagging UI + totals`.

### Task 5: Containerize

**Files:**
- Create: `apps-src/drivelog/Dockerfile`
- Create: `apps-src/drivelog/.dockerignore`

**Interfaces:** Consumes the package; produces a runnable image serving uvicorn on `:8080` (`CMD uvicorn drivelog.app:app --host 0.0.0.0 --port 8080`).

- [ ] **Step 1:** Write `Dockerfile` (python:3.12-slim, install pyproject deps, non-root user, EXPOSE 8080, healthcheck hitting `/healthz`).
- [ ] **Step 2: Build locally** — `docker build -t drivelog:dev apps-src/drivelog` → Expected: success.
- [ ] **Step 3: Smoke-run** — `docker run --rm -p 8080:8080 -e DRIVELOG_DB_... drivelog:dev` then `curl -f localhost:8080/healthz` → `{"status":"ok"}` (DB envs can point at a port-forwarded PG, or assert the container starts and /healthz responds without DB).
- [ ] **Step 4: Commit** — `build(drivelog): Dockerfile`.

### Task 6: GitHub Actions image build/push

**Files:**
- Create: `.github/workflows/drivelog-image.yml`

**Interfaces:** On push to `main` affecting `apps-src/drivelog/**`, and on `workflow_dispatch`: build and push `ghcr.io/cjchand/drivelog:latest` and `:<short-sha>` using `docker/build-push-action`, auth via `GITHUB_TOKEN` with `packages: write`.

- [ ] **Step 1:** Write the workflow (checkout, buildx, login to ghcr, build-push with both tags, `context: apps-src/drivelog`).
- [ ] **Step 2: Lint** — `yamllint`/`actionlint` if available, else visual check against `docker/build-push-action` docs.
- [ ] **Step 3: Commit** — `ci(drivelog): build & push image to ghcr`.
- [ ] **Step 4 (manual, post-merge):** Confirm the Action runs and the package appears at `ghcr.io/cjchand/drivelog`; make the package public or ensure the cluster can pull it (document which — mirror whatever `generate-dns-report` uses).

### Task 7: Kubernetes manifests + Flux wiring

**Files:**
- Create: `clusters/dev/apps/drivelog/deployment.yaml`
- Create: `clusters/dev/apps/drivelog/service.yaml`
- Create: `clusters/dev/apps/drivelog/ingress.yaml`
- Create: `clusters/dev/apps/drivelog/kustomization.yaml`
- Modify: `clusters/dev/apps/kustomization.yaml` (add `- drivelog/`)

**Interfaces:** Deployment in `teslamate` ns, image `ghcr.io/cjchand/drivelog:latest` (`imagePullPolicy: Always`), env from the `teslamate-postgres` secret (`teslamate_user_pass`) plus plain env (`DRIVELOG_DB_HOST=teslamate-pg-rw`, `DRIVELOG_DB_USER=teslamate`, `DRIVELOG_DB_NAME=teslamate`, `DRIVELOG_TZ=America/Chicago`, `DRIVELOG_STUDENT_NAME=Toby`, `DRIVELOG_HOME_LAT/LON`), readiness/liveness on `/healthz`, modest resources (start from `dns-report`'s values). Service :8080. Ingress host `drivelog.internal`, Traefik websecure, `internal-ca`, TLS secret `drivelog-tls`, homepage annotations (group "Lifestyle", icon teslamate/car).

- [ ] **Step 1:** Write all four manifests + add to apps kustomization. Do NOT create a namespace (teslamate exists).
- [ ] **Step 2: Validate** — `kubectl kustomize clusters/dev/apps/drivelog` renders cleanly; `kubectl apply --dry-run=server -k clusters/dev/apps/drivelog` (or client dry-run) passes.
- [ ] **Step 3: Commit** — `feat(drivelog): k8s manifests + flux wiring`.
- [ ] **Step 4 (manual, post-merge):** After Flux reconciles, browse `https://drivelog.internal`, tag a real drive, verify totals and that the `drivelog` schema was created without touching Teslamate tables.

---

## Self-Review Notes

- **Spec coverage:** weekly tagging UI (T4), day/night per Texas def (T1), 1-h/day cap night-first (T2), 30/10 totals + raw & capped (T2/T4), durable tags in `drivelog` schema (T3), read-only to Teslamate (T3, global constraint), GitOps deploy in teslamate ns reusing secret (T7), custom image via Action (T5/T6), no auth, untagged backlog filter (T4), two-car handling (T3/T4). All mapped.
- **Review Focus** inputs each have an owning test (NULL GPS→T1, in-progress drive→T3, midnight-spanning→T2, two cars→T3/T4, DST→T1).
- Correctness-critical logic is pure and unit-tested without a DB; DB/web tests are thinner by design.
