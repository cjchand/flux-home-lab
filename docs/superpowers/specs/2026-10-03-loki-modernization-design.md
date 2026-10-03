# Loki Modernization Design

**Date:** 2026-10-03
**Status:** Approved design, pending implementation plan

## Goal

Keep cluster logs collected and searchable *before* they are needed, while
replacing the deprecated `loki-stack` release (Loki 2.9 on boltdb-shipper,
Promtail, Grafana 10.3.3) with current, Renovate-tracked components.

### Success criteria

- Logs from every pod on all three nodes are searchable in Grafana at
  `grafana.internal`.
- No deprecated components remain: `loki-stack` and Promtail are gone, and
  Grafana is on 12.x.
- The Uptime Kuma monitor "Teslamate - Tesla API Reachable" is green against
  the new Loki.
- Grafana also serves the standard kube-prometheus-stack dashboards against
  Prometheus.

### Decisions already made

- Grafana moves into the existing kube-prometheus-stack release rather than
  a standalone chart.
- Nothing in the old Grafana is kept (no dashboards or users to export).
- Old log history is not migrated; the new Loki starts empty.
- Retention: 7 days default; 14 days for `kube-system`, `monitoring` and
  `teslamate` (TeslaMate drops from 30 days, since its only consumer looks
  back 7 hours).

## Architecture

All components live in the `monitoring` namespace.

| Component | Source | Role |
|---|---|---|
| Loki | `grafana/loki` 7.3.0 (Loki 3.6.x), new `loki/` app dir | Single-binary log store; service `loki:3100` |
| Alloy | `grafana/alloy` 1.13.0 (Alloy v1.20), new `alloy/` app dir | DaemonSet log collector replacing Promtail |
| Grafana | kube-prometheus-stack 91.8.2 Grafana subchart, `prometheus/` app dir | UI at `grafana.internal`; Prometheus + Loki datasources; default dashboards |

Both new charts use the existing `grafana` HelmRepository
(`https://grafana.github.io/helm-charts`) in `monitoring`, which currently
lives in `loki-stack/`; it moves to the `loki/` directory so it survives the
removal of `loki-stack/`.

## Configuration

### Loki

- `deploymentMode: SingleBinary`, `singleBinary.replicas: 1`.
- Storage: filesystem on a 10 GiB `nfs-client` PVC.
- Schema: `v13`, `store: tsdb`, `object_store: filesystem`, period 24h,
  starting from the deployment date.
- `auth_enabled: false`.
- Retention via the compactor (`retention_enabled: true`,
  `delete_request_store: filesystem`):
  - `limits_config.retention_period: 168h`
  - `retention_stream`: `{namespace=~"kube-system|monitoring|teslamate"}`
    at `336h`
  - `max_query_lookback: 336h`
- Explicitly disabled, because the chart defaults to large-scale settings:
  `chunksCache`, `resultsCache` (memcached, ~8 GB reserved by default),
  `gateway`, `minio`, `lokiCanary`, `test`, chart self-monitoring, and the
  SimpleScalable `read`/`write`/`backend` replicas (set to 0).
- Resources: requests 100m / 256Mi, limits 1 CPU / 1Gi. Revisit after
  observing real usage.

### Alloy

- DaemonSet on every node, `/var/log/pods` mounted read-only (the path
  Promtail uses today).
- Pipeline: `discovery.kubernetes` (pods, filtered to the local node) →
  `discovery.relabel` (labels plus `__path__` under `/var/log/pods`) →
  `local.file_match` → `loki.source.file` → `loki.process` with the CRI
  stage → `loki.write` to `http://loki:3100/loki/api/v1/push`. Reading files
  rather than streaming through the API server matches how Promtail works
  today and survives Alloy restarts via its positions file.
- Label parity with the current Promtail config: `namespace`, `app`,
  `instance`, `component`, `pod`, `container`, `node_name`,
  `job` (`<namespace>/<app>`). Existing queries such as
  `{namespace="teslamate"}` must work unchanged.
- Not included: Kubernetes event collection and the Alloy UI ingress.
- Resources: requests 25m / 64Mi, limits 200m / 256Mi.

### Grafana (kube-prometheus-stack)

- `grafana.enabled: true`, ingress `grafana.internal` via Traefik
  `websecure` with `internal-ca` TLS, carrying the same `gethomepage.dev/*`
  annotations as the old Grafana ingress.
- Admin credentials from a Sealed Secret (`admin.existingSecret`) holding a
  randomly generated password, which is handed to the user once.
- Persistence: 1 GiB `nfs-client` PVC for UI-created content only.
  Datasources and dashboards are provisioned from git.
- Loki datasource added via `grafana.additionalDataSources`, pointing at
  `http://loki.monitoring.svc.cluster.local:3100`. The Prometheus datasource
  comes with the chart.
- Default dashboards stay enabled.

### kube-prometheus-stack cleanup

Disable `kubeEtcd`, `kubeScheduler`, `kubeControllerManager` and
`kubeProxy`. On microk8s these run inside kubelite; their ServiceMonitors
exist but have 0 scrape targets. Disabling them removes empty dashboards and
alert rules that would otherwise report those components as permanently down.

### Docs

Update `docs/Applications/Monitoring.md`, `docs/Applications/README.md`,
`docs/Applications/monitor-queries/teslamate-tesla-api-reachable.md` (new
URL) and the directory tree in `docs/Flux/README.md`.

## Cutover

Side by side, one commit per step, each verified before the next:

1. **Deploy Loki and Alloy** alongside `loki-stack`. Promtail and the old
   Loki keep running.
2. **Switch Grafana.** Enable the kube-prometheus-stack Grafana and disable
   the `loki-stack` Grafana in the same commit, so `grafana.internal` moves
   over without two ingresses claiming the host. Disabling the old Grafana
   also deletes its Helm-managed PVC `loki-stack-grafana`; the
   `nfs-client` class has `archiveOnDelete: true`, so the provisioner
   renames its NAS directory to `archived-…` rather than erasing it.
3. **Repoint the Uptime Kuma monitor** (config lives in Uptime Kuma's
   database, not git). The user changes the URL host from `loki-stack` to
   `loki` in the UI, after the query has been verified against the new
   Loki.
4. **Remove `loki-stack`.** Remove it from the apps kustomization; Flux
   prunes it. The Loki PVC `storage-loki-stack-0` comes from a StatefulSet
   volumeClaimTemplate, so Helm leaves it behind; after user confirmation,
   delete it with kubectl. Its NFS directory, and the old Grafana's, are
   archived on the NAS as `archived-…`; removing those is a manual NAS task
   for the user, since the cluster has no access to delete them.

## Verification

Before any push:

- `helm template` each chart with our values; confirm no caches, gateway,
  MinIO or canary resources render.
- `kustomize build clusters/dev` succeeds; the Sealed Secret is sealed with
  the cluster's live certificate.

After each step:

| Step | Checks |
|---|---|
| 1 | Both HelmReleases Ready; one Alloy pod per node; Loki's label list includes `namespace`; `{namespace="teslamate"}` returns lines from the last few minutes; all three `node_name` values present |
| 2 | `grafana.internal` serves Grafana 12 and the new password works; both datasources pass Grafana's health check; "Kubernetes / Compute Resources / Cluster" shows data; Homepage lists Grafana |
| 3 | The monitor's exact query returns a non-empty result from the new Loki before the URL changes (once ~7h of logs exist); monitor green afterwards |
| 4 | `loki-stack` HelmRelease and pods gone; no remaining `loki-stack` references in `clusters/dev`; `storage-loki-stack-0` deleted; memory freed per `kubectl top` |

About one day after cutover: confirm compactor runs in Loki's logs.
Deletion at 7 and 14 days can only be observed once data reaches that age.

## Rollback

- **Steps 1–2:** `git revert` the step's commit. Promtail and the old Loki
  run throughout, so collection never stops. Reverting step 2 brings the old
  Grafana back with a new, empty PVC (the previous one is archived on the
  NAS); since nothing in it is being kept, that is acceptable.
- **Step 3:** change the monitor URL back in Uptime Kuma.
- **Step 4 is the point of no return.** Once `storage-loki-stack-0` is
  deleted, rollback means reinstalling `loki-stack` with empty storage. PVC
  deletion therefore waits for explicit user confirmation.

## Out of scope

- Kubernetes event collection.
- Scraping Traefik metrics or adding grafana.com community dashboards.
- Alerting / Alertmanager receivers.
