# Teslamate Postgres → CloudNativePG Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Teslamate's database off the Bitnami chart (`bitnamilegacy/postgresql:17.5.0`, StatefulSet `teslamate-postgres-nfs-postgresql-0`) onto a CNPG `Cluster`, with no data loss and a rollback path until the user signs off.

**Architecture:** A new CNPG `Cluster` named `teslamate-pg` copies the old database in when it is first created (`bootstrap.initdb.import`, type `microservice`), reading from the old Bitnami service as an `externalCluster`. Teslamate-core is stopped before the copy starts, so nothing is written after the snapshot. Row counts are compared before anything reconnects. The old database stays running, untouched, as the rollback until a later cleanup task.

**Tech Stack:** Flux CD, CloudNativePG operator 1.30.1 (`cluster-services-cloudnative-pg-operator`), PostgreSQL 17, Sealed Secrets, nfs-client storage.

**Spec:** None written; requirements come from the 2026-11-14 conversation ("start with Teslamate and make sure we don't lose data") and are copied into Global Constraints.

## Facts measured 2026-11-14

- Source: PostgreSQL 17.5, database `teslamate` 3.4 GB, `positions` 25,760,606 rows, `drives` 13,458, `charging_processes` 1,677, `schema_migrations` max `20261014120000`.
- Schemas: `public` (15 tables: 12 owned by `teslamate`, 3 by `postgres`) and `private` (1 table, 1 sequence). Extensions: `cube 1.5`, `earthdistance 1.2`.
- Roles: `postgres` (superuser), `teslamate` (login, DB owner is `postgres`).
- Clients:
  - teslamate-core connects as **`postgres`** (`postgres_user_pass`).
  - teslamate-grafana connects as **`teslamate`** (`teslamate_user_pass`).
  - Two Uptime Kuma monitors that were set up in the Kuma UI, not in git ("Postgres - Teslamate", "Teslamate - Data Freshness"), use `postgres://teslamate:…@teslamate-postgres-nfs-postgresql.teslamate.svc.cluster.local:5432/teslamate`.
  - The unbuilt drive-log plan (`docs/superpowers/plans/2026-11-14-teslamate-drive-log.md`) hardcodes that host too.
- There is **no backup today**. `teslamate-backup-pvc` (5Gi, nfs-client) exists, but nothing mounts it.
- A second, orphaned CNPG operator (`cloudnative-pg-operator`, v1.28.0, installed manually with Helm 2026-01-03, not in git) watches the same CRDs. The CRDs belong to the Flux-managed release and carry `helm.sh/resource-policy: keep`.

## Global Constraints

- The old database (StatefulSet, its PVC `data-teslamate-postgres-nfs-postgresql-0`, its HelmRelease) is **not modified or deleted** in this plan. Removal is Task 6, gated on the user's explicit OK after at least 7 days on CNPG.
- Teslamate-core must have **zero connections** to the old DB before the CNPG Cluster is created, and must stay stopped until Task 4's comparison passes.
- PostgreSQL major version stays **17**. No major upgrade during the migration.
- Passwords are unchanged. The existing `teslamate-postgres` secret, including `encryption_key`, keeps feeding teslamate-core and Grafana. New secrets only re-wrap the same values in the `kubernetes.io/basic-auth` shape CNPG requires (`username` + `password` keys; see commit `f4cdf33`).
- Plaintext secrets never get written to the repo or to disk outside the scratchpad, and are deleted after sealing.
- The user's preference: commit and push straight to `main`, no PRs.
- Run the cutover (Task 3 Step 4 to Task 4) only while every car is `asleep`/`offline`. Teslamate can't backfill drives that happen while it's stopped.

## Review Focus

1. **A write slipping in after the snapshot:** teslamate-core gets restarted by Flux, or still has an open connection, while the import runs. Expected: the import never starts while a `teslamate` DB connection exists from anything except psql. Pinned in Task 3 Step 3.
2. **Extension creation fails during the restore:** the restore runs as the non-superuser owner. Expected: `cube`/`earthdistance` exist in the new DB or the import fails loudly. Pinned in Task 4 Step 2 via `pg-inventory.sql`.
3. **Sequences behind the data:** a sequence restored behind its table's `max(id)` would cause duplicate-key errors on the first new position. Expected: every sequence's `last_value >= max(id)`. Pinned in `pg-inventory.sql`.
4. **Encrypted Tesla API tokens:** these live in the `private` schema. With a mismatched `ENCRYPTION_KEY`, Teslamate starts but can't call the API. Expected: core logs show the car's state updating within 15 minutes of resume. Pinned in Task 4 Step 5.
5. **Ownership change:** the restore makes `teslamate` own every object, including the 3 tables `postgres` owned before. Expected: core (superuser) and Grafana (`teslamate`) both work, and the next Teslamate schema migration runs. Pinned in Task 4 Step 5 (core starts without migration errors) and Step 6 (Grafana dashboards load).

---

### Task 1: Safety net: a verified dump of the current database

**Files:**
- Create: `scripts/pg-inventory.sql`

**Interfaces:**
- Produces: `scripts/pg-inventory.sql`, run with `psql -At -f`. It prints sorted lines in this exact format so two runs can be compared with `diff`:
  - `table|<schema>.<table>|<exact count(*)>` for every table in `public` and `private`;
  - `seq|<schema>.<seq>|ok` or `seq|<schema>.<seq>|BEHIND <last_value> < <max>` for every sequence owned by a column;
  - `ext|<name>|<version>` for every extension except `plpgsql`;
  - `migration|<max(version)>` from `public.schema_migrations`.

  Tasks 4 and 5 reuse it.
- Produces: `/backup/pre-cnpg-2026-11-14.dump` on `teslamate-backup-pvc`.

- [ ] **Step 1: Write `scripts/pg-inventory.sql`.** Use a `DO` block or `\gexec` to generate `count(*)` per table from `pg_tables`. Find each sequence's owning column through `pg_depend`/`pg_get_serial_sequence`. Add `ORDER BY` so output is stable across servers.
- [ ] **Step 2: Run it against the old DB and save the baseline.**
  `kubectl -n teslamate exec -i teslamate-postgres-nfs-postgresql-0 -- env PGPASSWORD=… psql -U postgres -d teslamate -At -f - < scripts/pg-inventory.sql > $SCRATCH/inventory-old-live.txt`
  Expected: 16 `table|` lines, `positions` ≥ 25,760,606, every `seq|…|ok`, `ext|cube|1.5`, `ext|earthdistance|1.2`, `migration|20261014120000` (or newer).
- [ ] **Step 3: Take a custom-format dump onto the backup PVC.** Use a one-off `kubectl run` pod with image `bitnamilegacy/postgresql:17.5.0-debian-12-r19` (the same client version as the server). Mount `teslamate-backup-pvc` at `/backup` and run `pg_dump -Fc -U postgres -h teslamate-postgres-nfs-postgresql -d teslamate -f /backup/pre-cnpg-2026-11-14.dump`.
  Expected: exit 0. The dump size gets reported to the user. The NFS provisioner doesn't enforce the 5Gi, and the NAS has about 1.5 TB free.
- [ ] **Step 4: Prove the dump restores.** In the same one-off pod, run `pg_restore --list /backup/pre-cnpg-2026-11-14.dump | grep -c "TABLE DATA"`.
  Expected: 16.
- [ ] **Step 5: Commit** `scripts/pg-inventory.sql`.
  Message: `Add a Postgres inventory query for verifying migrations`.

### Task 2: Remove the orphaned CNPG operator

**Files:** none. This is a manual Helm release outside git.

- [ ] **Step 1: Confirm no names are shared.** Diff the kinds/names in `helm -n cluster-services get manifest cloudnative-pg-operator` against `helm -n cluster-services get manifest cluster-services-cloudnative-pg-operator`.
  Expected: no Kind+name pair appears in both. The CRDs aren't in the orphan's manifest. **If any overlap exists, stop and report it to the user.**
- [ ] **Step 2: Get the user's explicit go-ahead,** then `helm -n cluster-services uninstall cloudnative-pg-operator`.
- [ ] **Step 3: Verify.**
  - `kubectl get crd clusters.postgresql.cnpg.io` still exists.
  - `kubectl -n cluster-services get deploy` shows only `cluster-services-cloudnative-pg-operator`, 1/1 Ready.
  - `flux get hr -n cluster-services cloudnative-pg-operator` reports Ready.

### Task 3: CNPG Cluster manifests, then stop Teslamate and import

**Files:**
- Create: `clusters/dev/apps/teslamate-postgres/cnpg-cluster.yaml`
- Create: `clusters/dev/apps/teslamate-postgres/cnpg-secrets-sealed.yaml`
- Modify: `clusters/dev/apps/teslamate-postgres/kustomization.yaml` (add both)

**Interfaces:**
- Produces:
  - Cluster `teslamate-pg` in namespace `teslamate`. Read/write service: `teslamate-pg-rw.teslamate.svc.cluster.local:5432`.
  - Sealed secrets `teslamate-pg-app` (`username: teslamate`, `password` = `teslamate_user_pass`) and `teslamate-pg-superuser` (`username: postgres`, `password` = `postgres_user_pass`), both `type: kubernetes.io/basic-auth`.

- [ ] **Step 1: Seal the two secrets** from the live `teslamate-postgres` values. Read them with `kubectl get secret … -o jsonpath | base64 -d` and build the plain Secret in the scratchpad. Seal it with the repo's documented `kubeseal --cert=pub-cert.pem --format=yaml` command into `cnpg-secrets-sealed.yaml`, then delete the plaintext.
- [ ] **Step 2: Write `cnpg-cluster.yaml`.**
  - `instances: 1`
  - `imageName: ghcr.io/cloudnative-pg/postgresql:17.<latest minor>`: look up the newest 17.x tag on ghcr.io at execution time and pin it.
  - `storage: {size: 20Gi, storageClass: nfs-client}`
  - `enableSuperuserAccess: true`, `superuserSecret.name: teslamate-pg-superuser`
  - `resources`: same requests/limits as the Bitnami `primary.resources`
  - `bootstrap.initdb`: `{database: teslamate, owner: teslamate, secret.name: teslamate-pg-app, import: {type: microservice, databases: [teslamate], source.externalCluster: bitnami-teslamate}}`
  - `externalClusters`: one entry `bitnami-teslamate` with `connectionParameters` `{host: teslamate-postgres-nfs-postgresql.teslamate.svc.cluster.local, user: postgres, dbname: teslamate, sslmode: disable}` and `password: {name: teslamate-postgres, key: postgres_user_pass}`.
- [ ] **Step 3: Stop Teslamate and prove nothing is writing.** Do this before pushing Step 4, and only while the car's open `states` row is `asleep` or `offline`.
  1. `flux suspend hr -n teslamate teslamate-core`
  2. `kubectl -n teslamate scale deploy teslamate-core --replicas=0`
  3. Run `select count(*) from pg_stat_activity where datname='teslamate' and application_name<>'psql'` on the old DB.

  Expected: `0`. Grafana opens connections only on page load; if it shows up, wait for it to close. **Don't continue while this is non-zero.**
- [ ] **Step 4: Re-take the baseline,** now frozen: re-run Task 1 Step 2 into `$SCRATCH/inventory-old-frozen.txt`. This file, not the live one, is the source of truth for Task 4.
- [ ] **Step 5: Validate, commit and push.**
  - `kubectl kustomize clusters/dev/apps/teslamate-postgres | kubectl apply --dry-run=server -f -` shows `cluster.postgresql.cnpg.io/teslamate-pg created` with no errors.
  - Commit: `Add CNPG cluster for Teslamate, importing from the Bitnami database`. Push to `main`, then `flux reconcile kustomization flux-system --with-source`.
- [ ] **Step 6: Wait for the import.** `kubectl -n teslamate get cluster teslamate-pg -w` until `Cluster in healthy state`. Watch the `teslamate-pg-1-import` job logs.
  Expected: the job completes, and the logs contain no `ERROR` lines from `pg_restore`. If the job fails, nothing has changed for the apps. Resume teslamate-core (`kubectl -n teslamate scale deploy teslamate-core --replicas=1` and `flux resume hr -n teslamate teslamate-core`), report the error, and stop.

### Task 4: Verify, then cut the clients over

**Files:**
- Modify: `clusters/dev/apps/teslamate-core/helmrelease.yaml:59` (`DATABASE_HOST` → `teslamate-pg-rw`)
- Modify: `clusters/dev/apps/teslamate-grafana/helmrelease.yaml:56` (`DATABASE_HOST` → `teslamate-pg-rw`)
- Modify: `docs/superpowers/plans/2026-11-14-teslamate-drive-log.md` (the 2 host references on lines 17 and 165 → `teslamate-pg-rw`)

**Interfaces:**
- Consumes: `teslamate-pg-rw`, `scripts/pg-inventory.sql`, `$SCRATCH/inventory-old-frozen.txt`.

- [ ] **Step 1: Run the inventory on the new DB.** Run it on `teslamate-pg-1` as `postgres` into `$SCRATCH/inventory-cnpg.txt`.
- [ ] **Step 2: Compare.** `diff $SCRATCH/inventory-old-frozen.txt $SCRATCH/inventory-cnpg.txt`.
  Expected: **no output**. Any difference (a row count, a `BEHIND` sequence, a missing extension or migration) is a hard stop. Teslamate-core stays stopped; report the diff to the user, who decides between fixing forward and rolling back by resuming core on the old host.
- [ ] **Step 3: Edit the 2 HelmReleases and the drive-log plan,** then validate with a server dry-run. Commit: `Point Teslamate at the CNPG database`. Push and reconcile.
- [ ] **Step 4: Resume Teslamate.** `flux resume hr -n teslamate teslamate-core`. Flux restores replicas and rolls the pod with the new host. Per memory, rollout restarts can run twice, so wait for the final pod.
- [ ] **Step 5: Verify core.**
  - Logs show a successful start with no Ecto migration errors.
  - Within 15 minutes, the newest `states` row in the new DB is updated.
  - On the next drive, `max(date)` in `positions` on `teslamate-pg-rw` advances past the frozen baseline.
  - Old DB: `pg_stat_activity` for `teslamate` shows 0 non-psql connections.
- [ ] **Step 6: Verify Grafana and Kuma.** The Grafana "Drives" and "Overview" dashboards load data through `teslamate-pg-rw`. Then update the two Kuma UI monitors' connection strings to `teslamate-pg-rw.teslamate.svc.cluster.local`. That's a manual UI edit or an `UPDATE` on `uptime_kuma.monitor`; the user picks. Expected: both monitors are green.

### Task 5: Nightly backups of the new database

**Files:**
- Create: `clusters/dev/apps/teslamate-postgres/cronjob-pg-dump.yaml`
- Modify: `clusters/dev/apps/teslamate-postgres/kustomization.yaml`

**Interfaces:**
- Consumes: `teslamate-pg-rw`, `teslamate-pg-superuser`, `teslamate-backup-pvc`.
- Produces: `/backup/teslamate-YYYY-MM-DD.dump` nightly, keeping the newest 7. `pre-cnpg-2026-11-14.dump` is never pruned.

- [ ] **Step 1: Write the CronJob.**
  - Schedule `30 3 * * *`, timeZone `America/Chicago`, `concurrencyPolicy: Forbid`.
  - Image: the same pinned `ghcr.io/cloudnative-pg/postgresql:17.x` as the Cluster.
  - Command: `pg_dump -Fc` to a temp name, `mv` to the final name on success, `pg_restore --list` sanity check, then prune by glob `teslamate-2*.dump` beyond 7.
  - Credentials from `teslamate-pg-superuser`. Match the house style of `cronjob-overnight-summary.yaml`.
- [ ] **Step 2: Dry-run, commit (`Back up Teslamate's database nightly`), push.**
- [ ] **Step 3: Trigger it once.** `kubectl -n teslamate create job --from=cronjob/teslamate-pg-dump manual-1`.
  Expected: the job completes, and `/backup/teslamate-<today>.dump` exists with a size within 10% of Task 1's dump.

### Task 6 (later, user-gated): Retire the Bitnami database

Not executed in this run. After at least 7 days on CNPG and the user's explicit OK:
- remove `helmrelease.yaml`, `teslamate-postgres-helmchart.yaml` and `source-helmrepo-bitnami.yaml` from `teslamate-postgres/` (confirm with `git grep` that nothing else uses the `bitnami` HelmRepository);
- delete the old PVCs, showing the user each one first: `data-teslamate-postgres-nfs-postgresql-0`, plus the 4-year-old hostpath `data-teslamate-postgres-postgresql-0`;
- update `docs/sealed-secrets.md`.

`pre-cnpg-2026-11-14.dump` stays.
