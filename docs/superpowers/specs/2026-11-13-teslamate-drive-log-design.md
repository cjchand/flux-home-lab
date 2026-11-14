# Teslamate Drive Log — Design

**Date:** 2026-11-13
**Status:** Draft for approval

## Intent / Why

Toby (the owner's son) is earning a Texas provisional driver license through a
parent-taught program (Aceable). Texas requires logged behind-the-wheel practice
that must be certified on **paper** forms filled out by hand:

- **30-Hour Behind-the-Wheel Log** (TEA/DPS): 20 daytime + **10 nighttime** = 30 h
  total, organized by skill module, with Date / Time / Daytime Hours / Nighttime
  Hours columns. Bold rule on the form: *"Only one (1) hour of behind-the-wheel
  instruction per day will count toward the 30 hours regardless of how many hours
  the student actually drives in a day."*
- **DL-91B 14-Hour In-Car Log**: 7 h in-car observation + 7 h behind-the-wheel.
  Only the behind-the-wheel half is actual driving; observation is the student as
  a passenger and is **not** trackable from vehicle data.

Teslamate already records every drive the car takes (start/end time, duration,
distance, GPS positions, start/end address & geofence) in PostgreSQL — but it
**cannot identify the driver**. The car logs the owner's own commutes mixed in
with Toby's practice. The owner needs a way to mark which drives were Toby's and
get clean, Texas-correct numbers to copy onto the paper logs.

The app is a **reference/aid**, not a submission system: the official logs are
still filled out and signed by hand. It removes the two tedious, error-prone
parts — separating Toby's drives from everyone else's, and computing the
day/night split — and tracks progress toward the 30 h / 10 night goal.

## Goals

- Show the car's drives, filterable by week, with enough detail (date, start
  time, duration, start/end location) to recognize each drive and place it on the
  correct skill row of the paper form.
- Let the owner **tag** each drive's driver (Toby / owner / untagged) with a
  single click, weekly, from a laptop browser.
- Compute, per tagged-as-Toby drive, the **daytime vs nighttime** minutes using
  the Texas legal definition of night (see below), splitting a drive that crosses
  the dusk/dawn boundary.
- Maintain running totals toward **30 h total / 10 h night**, applying the Texas
  **1-hour-per-day cap**, and show both capped ("counts") and raw figures so
  there are no surprises at the DPS counter.
- Persist tags durably so re-tagging is never needed and history is preserved.
- Deploy via the repo's existing GitOps conventions, in the `teslamate`
  namespace, reusing existing Postgres credentials.

## Non-Goals

- Not a replacement for the paper forms; does not generate a submittable/signed
  document. (Could be a later enhancement, e.g. a printable summary, but out of
  scope now.)
- Does not track **observation** hours (student as passenger) — not derivable
  from vehicle telemetry.
- Does not auto-detect the driver (impossible from Tesla API data).
- Does not assign drives to specific skill modules ("City Driving", etc.) — the
  owner does that by hand on the form, using the route/location as a memory aid.
- No multi-user accounts / authentication (internal network only).
- Does not modify any Teslamate-owned table.

## Anti-Goals (what makes this a failure even if it "works")

- Writing anything into Teslamate's own schema, or otherwise risking Teslamate's
  data or future chart migrations.
- Producing a night-hours number that disagrees with how Texas DPS would count it
  (wrong night definition, or not splitting boundary-crossing drives) — the whole
  point is a trustworthy number.
- Losing tags on redeploy / pod restart (tags must be in the database, not in
  memory or a pod volume).
- Requiring the owner to hand-edit SQL or spreadsheets — the weekly flow must be
  click-only.

## Key Domain Rules

- **Texas definition of night** (Transp. Code §541.401 defines *daytime* as the
  period from one-half hour before sunrise to one-half hour after sunset;
  nighttime is the complement): **night = from 30 min after sunset to 30 min
  before sunrise**, using actual sunset/sunrise for the drive's location and date.
- **Day/night split:** for each Toby drive, split the `[start, end]` interval at
  the night boundaries for that date/location and sum minutes on each side. A
  single drive can contribute to both day and night.
- **1-hour-per-day cap:** for the 30 h total, each calendar day contributes at
  most 60 minutes of *counted* time regardless of raw minutes driven. Owner
  confirmed they generally drive ~1 h/day, so this rarely bites, but it must be
  applied so totals match the form.
  - **Cap allocation rule (builder's call, documented):** when a day exceeds 60
    counted minutes and has both day and night driving, count **night minutes
    first** (night is the scarcer requirement), then day, up to the 60-minute cap.
    The 10-hour night sub-total is also computed from capped minutes so total and
    night stay internally consistent. Shown per-day in the UI.

## Constraints

- Must fit the repo's GitOps model: committed manifests under
  `clusters/dev/apps/`, reconciled by Flux; included in
  `clusters/dev/apps/kustomization.yaml`.
- Deploy in the **`teslamate`** namespace so it can mount the existing
  `teslamate-postgres` sealed secret.
- Ingress via Traefik with `cert-manager.io/cluster-issuer: internal-ca` and a
  `*.internal` host + TLS secret, matching the Teslamate ingress. Add Homepage
  (`gethomepage.dev/*`) annotations like the other apps.
- Custom image published to `ghcr.io/cjchand/drivelog` (mirrors
  `ghcr.io/cjchand/generate-dns-report`), pulled by a plain `Deployment` — **not**
  a HelmRelease (matches the `dns-report` app pattern of raw manifests +
  kustomization).

## Decisions Made (the "how", as decided)

- **Topology:** single container, internal web app at `drivelog.internal`.
- **Namespace:** `teslamate`.
- **Driver name:** "Toby" (configurable via env/config, default Toby).
- **Image build:** app source in a **new top-level folder in this repo**
  (proposed `apps-src/drivelog/`), built and pushed to
  `ghcr.io/cjchand/drivelog:latest` (and a commit-SHA tag) by a **new GitHub
  Actions workflow** (`.github/workflows/drivelog-image.yml`) triggered on changes
  to that folder. This is the repo's first CI workflow.
- **Manifests:** `clusters/dev/apps/drivelog/` with `namespace` reuse (teslamate
  already exists — do not recreate it), `deployment.yaml`, `service.yaml`,
  `ingress.yaml`, `kustomization.yaml`; add to `apps/kustomization.yaml`.
- **Storage:** a new PostgreSQL **schema `drivelog`** inside the **existing
  `teslamate` database**. The app only ever writes to this schema; it reads
  Teslamate's tables read-only. Reuse the `teslamate-postgres` secret.
- **Auth:** none; internal network only, consistent with Teslamate.
- **Stack (builder's call):** Python 3.12 + FastAPI, server-rendered HTML
  (Jinja2) with light vanilla JS for the checkboxes/week nav; `psycopg` (v3) for
  DB; `astral` for sunrise/sunset. No SPA framework. Rationale: tiny app, easy to
  maintain, no build toolchain beyond pip.

### Data model (`drivelog` schema)

- `drivers` — id, name, is_student (bool). Seed one student row "Toby".
  (Kept as a table rather than hard-coding so "owner"/other labels are possible,
  but UI can stay simple.)
- `drive_tags` — `teslamate_drive_id` (bigint, references the Teslamate
  `drives.id` value but **not** an enforced FK across schemas), `driver_id`,
  `tagged_at`. One row per tagged drive; untagged = no row. A drive tagged "not
  Toby / mine" is stored explicitly so it disappears from the untagged view.
- Optional `settings` — key/value for home location fallback, student name, goal
  hours (30/10) if the owner ever wants to override.

### How day/night is computed per drive

1. Get the drive's start location lat/lng from Teslamate (`drives.start_position_id`
   → `positions.latitude/longitude`; fall back to a configured home lat/lng if a
   position is missing).
2. With `astral`, compute sunrise/sunset for that date at that location; derive
   the night window edges (sunset +30 min, sunrise −30 min).
3. Intersect the drive's `[start_date, end_date]` (UTC in DB; convert to local
   America/Chicago for display and for the per-calendar-day cap) with day vs night
   windows; sum minutes each side. Handle drives spanning midnight.

### Pages / UX (validated via mockup)

- **Weekly screen** (default = current week): driver filter + week nav; three
  progress cards (total/30, night/10, days-logged); a table of that week's drives
  grouped by day, each row with a tag checkbox, day/night pills, a "counts"
  (capped) column, and route (start→end address/geofence). A save action persists
  tags. An "Untagged" filter view helps catch drives not yet classified.

## Open Questions Left to the Builder

- Exact Teslamate column names / join for start & end location labels (geofence
  name vs address) — verify against the live DB during implementation; prefer
  geofence name, fall back to address, then raw lat/lng.
- Whether to also surface a simple **all-time / "untagged backlog"** view in
  addition to per-week (mockup showed per-week; an untagged filter is planned).
- Minor: Deployment resource requests/limits (start from `dns-report`'s modest
  values), readiness/liveness probe paths.
- Whether the GitHub Action should also run on manual `workflow_dispatch` (assume
  yes) and whether to pin to `:latest` or require the SHA tag in the Deployment
  (assume `:latest` with `imagePullPolicy: Always`, matching `dns-report`).

## Testing / Verification Approach

- Unit tests for the day/night split and the 1-hour/day cap allocation (these are
  the correctness-critical, number-producing parts) — including boundary-crossing
  drives, drives entirely at night, midnight-spanning drives, and multi-drive
  days that exceed the cap.
- Manual verification against a few real Teslamate drives, spot-checking night
  minutes against known sunset times.
- Confirm the app cannot write outside the `drivelog` schema (DB grants or code
  discipline; document which).
