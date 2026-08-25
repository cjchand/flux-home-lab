# Monitor: "Teslamate - Tesla API Reachable"

Uptime Kuma monitor type **Keyword**, interval 1800s, 2 retries.

**URL** (Loki instant query, URL-encoded):

```
http://loki-stack.monitoring.svc.cluster.local:3100/loki/api/v1/query?query=sum%28count_over_time%28%7Bnamespace%3D%22teslamate%22%7D%20%7C%3D%20%22Scheduling%20token%20refresh%22%20%5B7h%5D%29%29%20%3E%200
```

Decoded LogQL:

```logql
sum(count_over_time({namespace="teslamate"} |= "Scheduling token refresh" [7h])) > 0
```

**Keyword:** `"value"` — not inverted.

## How it works

The `> 0` comparison is evaluated by Loki, so the result vector exists *only*
when the condition holds. Loki returns `"result":[]` otherwise, which contains
no `"value"` substring, so the keyword check fails and the monitor goes down.
This avoids needing numeric comparison in Uptime Kuma, and works on Loki
versions that reject `or vector(0)` (ours does).

`sum()` strips pod/filename labels so TeslaMate restarts don't churn the series.

## Why this specific signal

TeslaMate refreshes its Tesla OAuth token every 6 hours regardless of vehicle
state, and logs `Scheduling token refresh in 6 h`. Passing requires both that
the process is alive *and* that it can reach `auth.tesla.com`.

Nothing else works as a liveness signal:

- **The database cannot tell "asleep" from "pulls failing"** — both produce zero
  writes. `cars.updated_at` has not moved since 2025; there is no poll counter.
- **TeslaMate exposes no telemetry** — `/metrics`, `/healthz`, `/health` and
  `/api/health` all 404, and `DISABLE_MQTT=true`.
- **Error-count monitors are not liveness checks.** They only fire when
  TeslaMate is making calls that fail. If it wedges and makes no calls at all,
  zero errors are logged and the monitor stays green.
- The main data path is the **streaming WebSocket API**, which logs nothing per
  message. Over a 24h sample the entire log volume was 34 geocoding calls, 13
  API calls and 4 token refreshes.

## Coverage and the residual blind spot

| Failure | Caught by | Latency |
|---|---|---|
| Process dead / unresponsive | `Teslamate` (HTTP) | 60s |
| Alive but cannot reach Tesla API | this monitor | up to ~7h |
| Streaming broken while a car is online | `Teslamate - Data Freshness` | 15 min |
| Streaming broken while all cars asleep | **nothing** | — |

The last row is not fixable with the available signals: while every car sleeps
TeslaMate legitimately produces no data, and the only recurring log line is the
6-hourly token refresh. ~7h is the floor for detection during sleep.

**This monitor couples TeslaMate's health to Loki's.** If Loki or promtail
stops, it goes red. Read it as "TeslaMate or the log pipeline is broken."

## Known issue this surfaced

Every `vehicle_data` call over a 7-day sample returned HTTP 408 — 26 calls, 0
successes, 25 of them for car_id 2. `owner-api.teslamotors.com` is the legacy
Owner API that Tesla is retiring in favour of the Fleet API. The streaming path
still works, which is why positions still land, but the REST fallback is dead.
Worth investigating separately from monitoring.

There is also a recurring `GenServer :tzdata_release_updater terminating` crash
(tzdata 1.1.3 failing on a `24:00:00` value). Cosmetic so far.
