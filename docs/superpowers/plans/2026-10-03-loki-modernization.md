# Loki Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deprecated `loki-stack` release with Loki 3 (single binary), Grafana Alloy, and kube-prometheus-stack's Grafana, without a gap in log collection.

**Architecture:** Three Flux HelmReleases in the `monitoring` namespace: `loki` (new `apps/loki/`), `alloy` (new `apps/alloy/`), and Grafana enabled inside the existing `prometheus` release. The new stack runs alongside `loki-stack` until it is verified, then `loki-stack` is removed. Shared resources that currently live in `apps/loki-stack/` (the `monitoring` Namespace, the `grafana` HelmRepository, the Loki overview dashboard) are moved out first so removal cannot prune them.

**Tech Stack:** Flux CD v2 HelmReleases, Kustomize, `grafana/loki` 7.3.0, `grafana/alloy` 1.13.0, `kube-prometheus-stack` 91.8.2 (Grafana 13.2.3), Sealed Secrets (kubeseal 0.26), microk8s 1.33 with containerd.

**Spec:** `docs/superpowers/specs/2026-10-03-loki-modernization-design.md`

## Global Constraints

- Namespace for everything: `monitoring`.
- Loki chart `grafana/loki` version `7.3.0`; Alloy chart `grafana/alloy` version `1.13.0`; kube-prometheus-stack stays at `91.8.2`.
- Loki service URL used by every consumer: `http://loki.monitoring.svc.cluster.local:3100`.
- Retention: `retention_period: 168h`; `{namespace=~"kube-system|monitoring|teslamate"}` at `336h`; `max_query_lookback: 336h`.
- Loki schema: `v13`, `store: tsdb`, `object_store: filesystem`, from `2026-10-03`.
- Storage class `nfs-client` for all PVCs: Loki 10Gi, Grafana 1Gi.
- Grafana host `grafana.internal`, Traefik `websecure`, cluster issuer `internal-ca`, TLS secret `grafana-tls`.
- Grafana Loki datasource `uid: loki`.
- Grafana admin from SealedSecret `grafana-admin` with keys `admin-user` and `admin-password`.
- Label parity with Promtail: `namespace`, `app`, `instance`, `component`, `pod`, `container`, `node_name`, `job` (`<namespace>/<app>`).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Deploy = commit + `git push origin main` + `flux reconcile kustomization flux-system --with-source`.
- Never commit an unsealed Secret. Plain secret files go in the session scratchpad only.

## Review Focus

1. **Removing `apps/loki-stack/` prunes the `monitoring` Namespace** (it is defined there today), which would delete Prometheus, Uptime Kuma and its MariaDB. Expected: the Namespace survives every step. Pinned in Task 1 Step 1 and Task 5 Step 1.
2. **Alloy restarting re-reads every log file** if its positions file is not on persistent storage, duplicating lines in Loki. Expected: positions survive a pod restart. Pinned in Task 2 Step 6.
3. **Two Ingresses claiming `grafana.internal`** during the Grafana switch would route requests unpredictably. Expected: exactly one Ingress for the host at every commit. Pinned in Task 3 Step 6.
4. **The Uptime Kuma monitor going red after the URL switch** because the new Loki has under 7h of TeslaMate logs. Expected: the exact monitor query returns a non-empty result before the user changes the URL. Pinned in Task 4 Step 1.
5. **Loki chart defaults deploying large-scale components** (memcached reserving ~8 GB, gateway, MinIO, canary, read/write/backend replicas). Expected: only the single-binary StatefulSet and its Services render. Pinned in Task 1 Step 2.

---

### Task 1: Move shared resources out of loki-stack and deploy Loki

**Files:**
- Move: `clusters/dev/apps/loki-stack/namespace.yaml` → `clusters/dev/apps/prometheus/namespace.yaml`
- Move: `clusters/dev/apps/loki-stack/helm-repository.yaml` → `clusters/dev/apps/loki/helm-repository.yaml`
- Modify: `clusters/dev/apps/loki-stack/kustomization.yaml`
- Modify: `clusters/dev/apps/prometheus/kustomization.yaml`
- Create: `clusters/dev/apps/loki/helmrelease.yaml`
- Create: `clusters/dev/apps/loki/kustomization.yaml`
- Modify: `clusters/dev/apps/kustomization.yaml`

**Interfaces:**
- Produces: HelmRepository `grafana` in `monitoring` (used by Task 2); Service `loki` port 3100 in `monitoring` (used by Tasks 2, 3, 4); the `monitoring` Namespace now owned by `apps/prometheus/`.

Set `S` to the session scratchpad for every task:
`S=/private/tmp/claude-501/-Users-chandler-Projects-flux-home-lab/ed02c804-ea50-41d2-9b72-6208596d3451/scratchpad`

- [ ] **Step 1: Record which directory owns the Namespace and the HelmRepository (baseline)**

Run:
```bash
cd /Users/chandler/Projects/flux-home-lab
grep -rl -E 'kind: Namespace' clusters/dev/apps/*/ | xargs grep -l 'name: monitoring$'
grep -rl 'url: https://grafana.github.io/helm-charts' clusters/dev/apps/
```
Expected now: both print paths under `clusters/dev/apps/loki-stack/`. After Step 3 they must print `apps/prometheus/namespace.yaml` and `apps/loki/helm-repository.yaml`.

- [ ] **Step 2: Write a render check for Loki that fails before the values exist**

Create `$S/check-loki.sh`:
```bash
#!/bin/bash
# Fails unless the Loki HelmRelease values render to exactly the single-binary footprint.
set -euo pipefail
cd /Users/chandler/Projects/flux-home-lab
S=/private/tmp/claude-501/-Users-chandler-Projects-flux-home-lab/ed02c804-ea50-41d2-9b72-6208596d3451/scratchpad
f=clusters/dev/apps/loki/helmrelease.yaml
test -f "$f" || { echo "FAIL: $f missing"; exit 1; }
awk '/^  values:/{f=1;next} f{sub(/^    /,"");print}' "$f" > "$S/loki-values-check.yaml"
helm template loki grafana/loki --version 7.3.0 -n monitoring -f "$S/loki-values-check.yaml" > "$S/loki-render.yaml"
kinds=$(grep -E '^kind:' "$S/loki-render.yaml" | sort | uniq -c | tr -s ' ' | tr '\n' ';')
echo "kinds: $kinds"
[ "$(grep -c '^kind: StatefulSet' "$S/loki-render.yaml")" = 1 ] || { echo "FAIL: expected 1 StatefulSet"; exit 1; }
! grep -q '^kind: Deployment' "$S/loki-render.yaml" || { echo "FAIL: unexpected Deployment (gateway/cache?)"; exit 1; }
! grep -qiE 'memcached|minio|canary' "$S/loki-render.yaml" || { echo "FAIL: cache/minio/canary rendered"; exit 1; }
! grep -q 'loki-sc-rules' "$S/loki-render.yaml" || { echo "FAIL: rules sidecar rendered"; exit 1; }
for s in 'retention_period: 168h' 'period: 336h' 'max_query_lookback: 336h' 'retention_enabled: true' 'schema: v13' 'store: tsdb' 'replication_factor: 1' 'auth_enabled: false'; do
  grep -q "$s" "$S/loki-render.yaml" || { echo "FAIL: config missing '$s'"; exit 1; }
done
grep -q 'storageClassName: nfs-client' "$S/loki-render.yaml" || { echo "FAIL: PVC not on nfs-client"; exit 1; }
echo PASS
```
Run: `chmod +x $S/check-loki.sh && $S/check-loki.sh`
Expected: `FAIL: clusters/dev/apps/loki/helmrelease.yaml missing`

- [ ] **Step 3: Move the shared resources**

```bash
cd /Users/chandler/Projects/flux-home-lab
mkdir -p clusters/dev/apps/loki
git mv clusters/dev/apps/loki-stack/namespace.yaml clusters/dev/apps/prometheus/namespace.yaml
git mv clusters/dev/apps/loki-stack/helm-repository.yaml clusters/dev/apps/loki/helm-repository.yaml
```

Replace `clusters/dev/apps/loki-stack/kustomization.yaml` with:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - helmrelease.yaml
  - grafana-dashboard-configmap.yaml
```

Replace `clusters/dev/apps/prometheus/kustomization.yaml` with:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - namespace.yaml
  - helm-repository.yaml
  - helmrelease.yaml
```

- [ ] **Step 4: Create the Loki HelmRelease**

Create `clusters/dev/apps/loki/helmrelease.yaml`:
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: loki
  namespace: monitoring
spec:
  interval: 1h
  chart:
    spec:
      chart: loki
      version: "7.3.0"
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: monitoring
  values:
    # One Loki process with filesystem storage on NFS. The chart defaults to
    # SimpleScalable with memcached caches (~8 GB reserved), a gateway, MinIO
    # and a canary; everything below that is set to 0/false turns those off.
    deploymentMode: SingleBinary

    loki:
      auth_enabled: false
      commonConfig:
        replication_factor: 1
      storage:
        type: filesystem
      schemaConfig:
        configs:
          - from: "2026-10-03"
            store: tsdb
            object_store: filesystem
            schema: v13
            index:
              prefix: index_
              period: 24h
      limits_config:
        retention_period: 168h    # 7 days by default
        retention_stream:
          - selector: '{namespace=~"kube-system|monitoring|teslamate"}'
            priority: 1
            period: 336h          # 14 days
        max_query_lookback: 336h
      compactor:
        retention_enabled: true
        delete_request_store: filesystem

    singleBinary:
      replicas: 1
      persistence:
        storageClass: nfs-client
        size: 10Gi
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          cpu: "1"
          memory: 1Gi

    read:
      replicas: 0
    write:
      replicas: 0
    backend:
      replicas: 0

    chunksCache:
      enabled: false
    resultsCache:
      enabled: false
    gateway:
      enabled: false
    minio:
      enabled: false
    lokiCanary:
      enabled: false
    test:
      enabled: false
    # No alerting/recording rules are loaded from ConfigMaps.
    sidecar:
      rules:
        enabled: false
```

Create `clusters/dev/apps/loki/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - helm-repository.yaml
  - helmrelease.yaml
```

In `clusters/dev/apps/kustomization.yaml`, add `  - loki/` on the line before `  - loki-stack/`.

- [ ] **Step 5: Run the checks and verify they pass**

Run:
```bash
$S/check-loki.sh
cd /Users/chandler/Projects/flux-home-lab
kustomize build clusters/dev > $S/build.yaml && echo "build OK"
grep -c -E '^kind: Namespace' $S/build.yaml
grep -A3 '^kind: Namespace' $S/build.yaml | grep -c 'name: monitoring$'
grep -rl -E 'kind: Namespace' clusters/dev/apps/*/ | xargs grep -l 'name: monitoring$'
grep -rl 'url: https://grafana.github.io/helm-charts' clusters/dev/apps/
```
Expected: `PASS`; `build OK`; the monitoring Namespace count is exactly `1`; the Namespace path is `clusters/dev/apps/prometheus/namespace.yaml`; the HelmRepository path is `clusters/dev/apps/loki/helm-repository.yaml`.

- [ ] **Step 6: Commit, push, reconcile**

```bash
cd /Users/chandler/Projects/flux-home-lab
git add -A clusters/dev/apps
git commit -F - <<'EOF'
Deploy Loki 3 in single-binary mode alongside loki-stack

First step of replacing the deprecated loki-stack release (see
docs/superpowers/specs/2026-10-03-loki-modernization-design.md).

Loki 3.6 runs as one process with tsdb/v13 filesystem storage on a 10Gi
NFS volume. Retention is 7 days, with 14 days for kube-system,
monitoring and teslamate. The chart's large-scale defaults (memcached
caches, gateway, MinIO, canary, read/write/backend replicas) are turned
off explicitly.

The monitoring Namespace and the grafana HelmRepository were defined
inside apps/loki-stack/. They move to apps/prometheus/ and apps/loki/
so that removing loki-stack later cannot prune them; pruning the
Namespace would take Prometheus, Uptime Kuma and its MariaDB with it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
flux reconcile kustomization flux-system --with-source
```

- [ ] **Step 7: Verify in the cluster**

Run:
```bash
kubectl wait -n monitoring hr/loki --for=condition=Ready --timeout=10m
kubectl -n monitoring get pods -l app.kubernetes.io/name=loki
kubectl -n monitoring get pvc storage-loki-0
kubectl get ns monitoring
kubectl -n monitoring get hr loki-stack prometheus uptime-kuma
kubectl -n monitoring exec loki-0 -c loki -- wget -qO- http://localhost:3100/ready
```
Expected: HelmRelease `loki` Ready; one pod `loki-0` 2/2 or 1/1 Running; PVC Bound on `nfs-client`; Namespace `monitoring` Active (age unchanged, years old); the three existing HelmReleases still Ready; `/ready` prints `ready`.

---

### Task 2: Deploy Alloy and verify logs flow into Loki

**Files:**
- Create: `clusters/dev/apps/alloy/helmrelease.yaml`
- Create: `clusters/dev/apps/alloy/kustomization.yaml`
- Modify: `clusters/dev/apps/kustomization.yaml`

**Interfaces:**
- Consumes: HelmRepository `grafana` and Service `loki:3100` from Task 1.
- Produces: log streams in Loki carrying the labels from Global Constraints (used by Tasks 3 and 4).

- [ ] **Step 1: Write a config check that fails before the file exists**

Create `$S/check-alloy.sh`:
```bash
#!/bin/bash
# Fails unless the Alloy HelmRelease renders a DaemonSet with a valid Alloy config.
set -euo pipefail
cd /Users/chandler/Projects/flux-home-lab
S=/private/tmp/claude-501/-Users-chandler-Projects-flux-home-lab/ed02c804-ea50-41d2-9b72-6208596d3451/scratchpad
f=clusters/dev/apps/alloy/helmrelease.yaml
test -f "$f" || { echo "FAIL: $f missing"; exit 1; }
awk '/^  values:/{f=1;next} f{sub(/^    /,"");print}' "$f" > "$S/alloy-values-check.yaml"
helm template alloy grafana/alloy --version 1.13.0 -n monitoring -f "$S/alloy-values-check.yaml" > "$S/alloy-render.yaml"
[ "$(grep -c '^kind: DaemonSet' "$S/alloy-render.yaml")" = 1 ] || { echo "FAIL: expected 1 DaemonSet"; exit 1; }
grep -q -- '--storage.path=/var/lib/alloy/data' "$S/alloy-render.yaml" || { echo "FAIL: storage path not on hostPath"; exit 1; }
grep -q 'path: /var/lib/alloy' "$S/alloy-render.yaml" || { echo "FAIL: /var/lib/alloy hostPath missing"; exit 1; }
grep -q 'path: /var/log$' "$S/alloy-render.yaml" || { echo "FAIL: /var/log hostPath missing"; exit 1; }
awk '/^    content: \|/{f=1;next} f&&/^[a-z]/{f=0} f{sub(/^      /,"");print}' "$S/alloy-values-check.yaml" > "$S/config.alloy"
docker run --rm -e K8S_NODE_NAME=x -v "$S/config.alloy:/etc/alloy/config.alloy" grafana/alloy:v1.20.0 validate /etc/alloy/config.alloy || { echo "FAIL: alloy validate"; exit 1; }
for l in namespace app instance component pod container node_name job __path__; do
  grep -q "target_label  = \"$l\"" "$S/config.alloy" || { echo "FAIL: no rule for label $l"; exit 1; }
done
echo PASS
```
Run: `chmod +x $S/check-alloy.sh && $S/check-alloy.sh`
Expected: `FAIL: clusters/dev/apps/alloy/helmrelease.yaml missing`

- [ ] **Step 2: Create the Alloy HelmRelease**

Create `clusters/dev/apps/alloy/helmrelease.yaml`:
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: alloy
  namespace: monitoring
spec:
  interval: 1h
  chart:
    spec:
      chart: alloy
      version: "1.13.0"
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: monitoring
  values:
    controller:
      type: daemonset
      volumes:
        extra:
          # Read positions live on the host so a pod restart resumes where it
          # left off instead of re-reading (and duplicating) every log file.
          - name: alloy-data
            hostPath:
              path: /var/lib/alloy
              type: DirectoryOrCreate

    alloy:
      storagePath: /var/lib/alloy/data
      mounts:
        varlog: true
        extra:
          - name: alloy-data
            mountPath: /var/lib/alloy
      resources:
        requests:
          cpu: 25m
          memory: 64Mi
        limits:
          cpu: 200m
          memory: 256Mi
      # Labels mirror the Promtail config this replaces, so existing LogQL
      # (e.g. the Uptime Kuma TeslaMate monitor) keeps working unchanged.
      configMap:
        content: |
          discovery.kubernetes "pods" {
            role = "pod"
            selectors {
              role  = "pod"
              field = "spec.nodeName=" + sys.env("K8S_NODE_NAME")
            }
          }

          discovery.relabel "pod_logs" {
            targets = discovery.kubernetes.pods.targets

            rule {
              source_labels = ["__meta_kubernetes_pod_controller_name"]
              regex         = "([0-9a-z-.]+?)(-[0-9a-f]{8,10})?"
              target_label  = "__tmp_controller_name"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_label_app_kubernetes_io_name", "__meta_kubernetes_pod_label_app", "__tmp_controller_name", "__meta_kubernetes_pod_name"]
              regex         = "^;*([^;]+)(;.*)?$"
              target_label  = "app"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_label_app_kubernetes_io_instance", "__meta_kubernetes_pod_label_release"]
              regex         = "^;*([^;]+)(;.*)?$"
              target_label  = "instance"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_label_app_kubernetes_io_component", "__meta_kubernetes_pod_label_component"]
              regex         = "^;*([^;]+)(;.*)?$"
              target_label  = "component"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_node_name"]
              target_label  = "node_name"
            }
            rule {
              source_labels = ["__meta_kubernetes_namespace"]
              target_label  = "namespace"
            }
            rule {
              source_labels = ["namespace", "app"]
              separator     = "/"
              target_label  = "job"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_name"]
              target_label  = "pod"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_container_name"]
              target_label  = "container"
            }
            rule {
              source_labels = ["__meta_kubernetes_pod_uid", "__meta_kubernetes_pod_container_name"]
              separator     = "/"
              replacement   = "/var/log/pods/*$1/*.log"
              target_label  = "__path__"
            }
            // Static pods log under their config hash rather than their UID.
            rule {
              source_labels = ["__meta_kubernetes_pod_annotationpresent_kubernetes_io_config_hash", "__meta_kubernetes_pod_annotation_kubernetes_io_config_hash", "__meta_kubernetes_pod_container_name"]
              separator     = "/"
              regex         = "true/(.*)"
              replacement   = "/var/log/pods/*$1/*.log"
              target_label  = "__path__"
            }
          }

          local.file_match "pod_logs" {
            path_targets = discovery.relabel.pod_logs.output
          }

          loki.source.file "pod_logs" {
            targets    = local.file_match.pod_logs.targets
            forward_to = [loki.process.pod_logs.receiver]
          }

          loki.process "pod_logs" {
            stage.cri {}
            forward_to = [loki.write.default.receiver]
          }

          loki.write "default" {
            endpoint {
              url = "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
            }
          }
```

Create `clusters/dev/apps/alloy/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - helmrelease.yaml
```

In `clusters/dev/apps/kustomization.yaml`, add `  - alloy/` as the first entry under `resources:`.

- [ ] **Step 3: Run the checks and verify they pass**

Run: `$S/check-alloy.sh && (cd /Users/chandler/Projects/flux-home-lab && kustomize build clusters/dev >/dev/null && echo "build OK")`
Expected: `PASS` and `build OK`.

- [ ] **Step 4: Commit, push, reconcile**

```bash
cd /Users/chandler/Projects/flux-home-lab
git add clusters/dev/apps/alloy clusters/dev/apps/kustomization.yaml
git commit -F - <<'EOF'
Collect pod logs into the new Loki with Grafana Alloy

Alloy replaces Promtail, which is deprecated upstream. It runs as a
DaemonSet, tails /var/log/pods on its own node, parses the CRI format
and pushes to loki:3100. The relabel rules mirror the current Promtail
config, so streams carry the same namespace/app/instance/component/
pod/container/node_name/job labels and existing LogQL keeps working.

Read positions are stored on a /var/lib/alloy hostPath instead of the
chart's /tmp default, so a pod restart resumes rather than re-reading
and duplicating every file.

Promtail keeps feeding loki-stack until the cutover is verified.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
flux reconcile kustomization flux-system --with-source
```

- [ ] **Step 5: Verify logs arrive from every node with the expected labels**

Run:
```bash
kubectl wait -n monitoring hr/alloy --for=condition=Ready --timeout=10m
kubectl -n monitoring get ds alloy
kubectl -n monitoring logs ds/alloy -c alloy --tail=200 | grep -i -E 'level=(error|warn)' | head
sleep 60
L='kubectl -n monitoring exec loki-0 -c loki -- wget -qO-'
$L 'http://localhost:3100/loki/api/v1/labels'; echo
$L 'http://localhost:3100/loki/api/v1/label/node_name/values'; echo
$L 'http://localhost:3100/loki/api/v1/query?query=sum%20by%20(namespace)%20(count_over_time(%7Bnamespace%3D~%22.%2B%22%7D%5B5m%5D))' | python3 -c 'import json,sys;[print(r["metric"].get("namespace"),r["value"][1]) for r in json.load(sys.stdin)["data"]["result"]]'
$L 'http://localhost:3100/loki/api/v1/query?query=count_over_time(%7Bnamespace%3D%22teslamate%22%7D%5B5m%5D)' | head -c 300; echo
```
Expected: DESIRED = READY = 3; no error/warn lines other than "entry too far behind" rejections for log lines older than 7 days (harmless); the labels list includes every label from Global Constraints; `node_name` values are `microk8s-node-01`, `microk8s-node-03`, `microk8s-node-04`; lines counted for many namespaces including `teslamate`; the TeslaMate query has a non-empty `result`.

- [ ] **Step 6: Verify read positions survive a pod restart (Review Focus 2)**

Run:
```bash
P=$(kubectl -n monitoring get pod -l app.kubernetes.io/name=alloy -o jsonpath='{.items[0].metadata.name}')
N=$(kubectl -n monitoring get pod $P -o jsonpath='{.spec.nodeName}')
kubectl -n monitoring exec $P -c alloy -- find /var/lib/alloy/data -name 'positions.yml' -exec wc -l {} \;
kubectl -n monitoring delete pod $P
kubectl -n monitoring wait pod -l app.kubernetes.io/name=alloy --field-selector spec.nodeName=$N --for=condition=Ready --timeout=2m
P2=$(kubectl -n monitoring get pod -l app.kubernetes.io/name=alloy --field-selector spec.nodeName=$N -o jsonpath='{.items[0].metadata.name}')
kubectl -n monitoring exec $P2 -c alloy -- find /var/lib/alloy/data -name 'positions.yml' -exec wc -l {} \;
kubectl -n monitoring logs $P2 -c alloy | grep -c -i 'start tailing' 
kubectl -n monitoring logs $P2 -c alloy | grep -i -E 'seek|position' | head -5
```
Expected: the positions file exists before the restart with one entry per tailed file, and still exists with a similar line count after it (the same host directory); the new pod's log shows files resuming at saved positions instead of position 0.

---

### Task 3: Move Grafana into kube-prometheus-stack

**Files:**
- Create: `clusters/dev/apps/prometheus/grafana-admin-sealedsecret.yaml`
- Modify: `clusters/dev/apps/prometheus/helmrelease.yaml`
- Modify: `clusters/dev/apps/prometheus/kustomization.yaml`
- Move: `clusters/dev/apps/loki-stack/grafana-dashboard-configmap.yaml` → `clusters/dev/apps/loki/grafana-dashboard-configmap.yaml` (datasource uid `loki-stack` → `loki`)
- Modify: `clusters/dev/apps/loki/kustomization.yaml`
- Modify: `clusters/dev/apps/loki-stack/helmrelease.yaml` (disable its Grafana)
- Modify: `clusters/dev/apps/loki-stack/kustomization.yaml`

**Interfaces:**
- Consumes: Service `loki:3100` and the labels from Task 2.
- Produces: Grafana at `https://grafana.internal` with datasources `Prometheus` and `Loki` (uid `loki`).

- [ ] **Step 1: Write a render check that fails before the change**

Create `$S/check-grafana.sh`:
```bash
#!/bin/bash
# Fails unless kube-prometheus-stack renders Grafana wired the way the spec requires,
# and only one Ingress in the whole build claims grafana.internal.
set -euo pipefail
cd /Users/chandler/Projects/flux-home-lab
S=/private/tmp/claude-501/-Users-chandler-Projects-flux-home-lab/ed02c804-ea50-41d2-9b72-6208596d3451/scratchpad
awk '/^  values:/{f=1;next} f{sub(/^    /,"");print}' clusters/dev/apps/prometheus/helmrelease.yaml > "$S/kps-values-check.yaml"
helm template prometheus oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack --version 91.8.2 -n monitoring -f "$S/kps-values-check.yaml" > "$S/kps-render.yaml" 2>/dev/null
grep -q 'image: "docker.io/grafana/grafana' "$S/kps-render.yaml" || { echo "FAIL: Grafana not rendered"; exit 1; }
grep -q 'uid: loki$' "$S/kps-render.yaml" || { echo "FAIL: Loki datasource uid loki missing"; exit 1; }
grep -q 'url: http://loki.monitoring.svc.cluster.local:3100' "$S/kps-render.yaml" || { echo "FAIL: Loki datasource URL"; exit 1; }
grep -A2 'GF_SECURITY_ADMIN_PASSWORD' "$S/kps-render.yaml" | grep -q 'grafana-admin' || { echo "FAIL: admin password not from grafana-admin secret"; exit 1; }
! grep -qE 'name: prometheus-kube-prometheus-(etcd|scheduler|controller-manager|proxy)$' "$S/kps-render.yaml" || { echo "FAIL: microk8s-irrelevant dashboards still rendered"; exit 1; }
# The loki-stack chart renders its Grafana Ingress only when grafana.enabled is true.
awk '/^  values:/{f=1;next} f{sub(/^    /,"");print}' clusters/dev/apps/loki-stack/helmrelease.yaml > "$S/ls-values-check.yaml"
helm template loki-stack grafana/loki-stack --version 2.10.3 -n monitoring -f "$S/ls-values-check.yaml" > "$S/ls-render.yaml"
hosts=$(cat "$S/kps-render.yaml" "$S/ls-render.yaml" | grep -c -E '^\s+- host: "?grafana.internal"?$' || true)
[ "$hosts" = 1 ] || { echo "FAIL: $hosts Ingress rules claim grafana.internal (want 1)"; exit 1; }
grep -q '"uid": "loki"' clusters/dev/apps/loki/grafana-dashboard-configmap.yaml || { echo "FAIL: dashboard not moved/retargeted"; exit 1; }
! grep -q '"uid": "loki-stack"' clusters/dev/apps/loki/grafana-dashboard-configmap.yaml || { echo "FAIL: dashboard still points at loki-stack"; exit 1; }
echo PASS
```
Run: `chmod +x $S/check-grafana.sh && $S/check-grafana.sh`
Expected: `FAIL: Grafana not rendered`

- [ ] **Step 2: Create and seal the admin Secret**

```bash
cd /Users/chandler/Projects/flux-home-lab
PW=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
kubectl create secret generic grafana-admin -n monitoring \
  --from-literal=admin-user=admin --from-literal=admin-password="$PW" \
  --dry-run=client -o yaml > $S/grafana-admin.yaml
kubeseal --fetch-cert --controller-name=sealed-secrets-controller --controller-namespace=flux-system > $S/pub-cert.pem
kubeseal --cert=$S/pub-cert.pem --format=yaml < $S/grafana-admin.yaml > clusters/dev/apps/prometheus/grafana-admin-sealedsecret.yaml
echo "$PW" > $S/grafana-admin-password.txt
rm $S/grafana-admin.yaml
grep -c -E 'admin-user|admin-password' clusters/dev/apps/prometheus/grafana-admin-sealedsecret.yaml
grep -q "$PW" clusters/dev/apps/prometheus/grafana-admin-sealedsecret.yaml && echo "LEAK" || echo "sealed OK"
```
Expected: `2` and `sealed OK`. The password is kept only in `$S/grafana-admin-password.txt` and is given to the user once, in Step 7.

Replace `clusters/dev/apps/prometheus/kustomization.yaml` with:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - namespace.yaml
  - helm-repository.yaml
  - grafana-admin-sealedsecret.yaml
  - helmrelease.yaml
```

- [ ] **Step 3: Enable Grafana in kube-prometheus-stack**

In `clusters/dev/apps/prometheus/helmrelease.yaml`, replace the block
```yaml
    # Grafana is already provided by the loki-stack release (grafana.internal);
    # Prometheus is wired into it as a datasource instead of running a second Grafana.
    grafana:
      enabled: false
```
with:
```yaml
    # The cluster's only general-purpose Grafana (TeslaMate runs its own).
    # Datasources and dashboards are provisioned from git; the PVC only holds
    # anything created in the UI.
    grafana:
      enabled: true
      admin:
        existingSecret: grafana-admin
        userKey: admin-user
        passwordKey: admin-password
      persistence:
        enabled: true
        storageClassName: nfs-client
        accessModes: ["ReadWriteOnce"]
        size: 1Gi
      ingress:
        enabled: true
        ingressClassName: traefik
        annotations:
          traefik.ingress.kubernetes.io/router.entrypoints: websecure
          traefik.ingress.kubernetes.io/router.tls: "true"
          cert-manager.io/cluster-issuer: internal-ca
          gethomepage.dev/enabled: "true"
          gethomepage.dev/description: Dashboards
          gethomepage.dev/group: Monitoring
          gethomepage.dev/name: "Grafana"
          gethomepage.dev/icon: "grafana.png"
        hosts:
          - grafana.internal
        path: /
        tls:
          - hosts:
              - grafana.internal
            secretName: grafana-tls
      additionalDataSources:
        - name: Loki
          type: loki
          uid: loki
          url: http://loki.monitoring.svc.cluster.local:3100
          access: proxy
      resources:
        requests:
          cpu: 50m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 512Mi

    # microk8s runs etcd, the scheduler, controller-manager and kube-proxy
    # inside kubelite, so these ServiceMonitors never find a target. Disabling
    # them drops their empty dashboards and their always-firing "down" alerts.
    kubeEtcd:
      enabled: false
    kubeScheduler:
      enabled: false
    kubeControllerManager:
      enabled: false
    kubeProxy:
      enabled: false
```

- [ ] **Step 4: Turn off the loki-stack Grafana and move the Loki dashboard**

In `clusters/dev/apps/loki-stack/helmrelease.yaml`, replace the entire `    grafana:` block (from `    # Grafana configuration` through the Grafana `resources:` block that ends just before `    # Promtail configuration for log collection`) with:
```yaml
    # Grafana moved to the kube-prometheus-stack release (apps/prometheus/).
    grafana:
      enabled: false

```

Move and retarget the dashboard:
```bash
cd /Users/chandler/Projects/flux-home-lab
git mv clusters/dev/apps/loki-stack/grafana-dashboard-configmap.yaml clusters/dev/apps/loki/grafana-dashboard-configmap.yaml
sed -i '' 's/"uid": "loki-stack"/"uid": "loki"/' clusters/dev/apps/loki/grafana-dashboard-configmap.yaml
grep -c '"uid": "loki"$' clusters/dev/apps/loki/grafana-dashboard-configmap.yaml
```
Expected: the count equals the number of former `loki-stack` references (`grep -c` before the sed shows the same number).

Replace `clusters/dev/apps/loki/kustomization.yaml` with:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - helm-repository.yaml
  - helmrelease.yaml
  - grafana-dashboard-configmap.yaml
```

Replace `clusters/dev/apps/loki-stack/kustomization.yaml` with:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - helmrelease.yaml
```

- [ ] **Step 5: Run the checks and verify they pass**

Run: `$S/check-grafana.sh && (cd /Users/chandler/Projects/flux-home-lab && kustomize build clusters/dev >/dev/null && echo "build OK")`
Expected: `PASS` and `build OK`.

- [ ] **Step 6: Commit, push, reconcile**

```bash
cd /Users/chandler/Projects/flux-home-lab
git add -A clusters/dev/apps
git commit -F - <<'EOF'
Move Grafana into kube-prometheus-stack

Grafana now comes from the kube-prometheus-stack release instead of
loki-stack, which pinned it at 10.3.3. It is provisioned from git with
the Prometheus datasource, a Loki datasource pointing at the new Loki,
and the chart's default Kubernetes dashboards. Admin credentials come
from a SealedSecret instead of a plaintext password in values.

The loki-stack Grafana is disabled in the same commit, so only one
Ingress claims grafana.internal at any point. Its PVC is archived on
the NAS by the nfs-client provisioner.

The Loki overview dashboard moves to apps/loki/ and now targets the
new datasource uid.

Also disables kubeEtcd, kubeScheduler, kubeControllerManager and
kubeProxy: microk8s runs them inside kubelite, so their ServiceMonitors
had 0 targets, their dashboards were empty and their alerts reported
them as permanently down.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
flux reconcile kustomization flux-system --with-source
```

- [ ] **Step 7: Verify Grafana end to end (Review Focus 3)**

Run:
```bash
kubectl wait -n monitoring hr/prometheus hr/loki-stack --for=condition=Ready --timeout=10m
kubectl get ingress -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.rules[*].host}{"\n"}{end}' | grep -c 'grafana.internal'
kubectl -n monitoring get pods | grep -i grafana
PW=$(cat $S/grafana-admin-password.txt)
curl -sk -u "admin:$PW" https://grafana.internal/api/health; echo
curl -sk -u "admin:$PW" https://grafana.internal/api/datasources | python3 -c 'import json,sys;[print(d["name"],d["uid"],d["url"]) for d in json.load(sys.stdin)]'
for uid in $(curl -sk -u "admin:$PW" https://grafana.internal/api/datasources | python3 -c 'import json,sys;print(" ".join(d["uid"] for d in json.load(sys.stdin)))'); do
  echo "$uid: $(curl -sk -u "admin:$PW" https://grafana.internal/api/datasources/uid/$uid/health)"; done
curl -sk -u "admin:$PW" 'https://grafana.internal/api/search?type=dash-db' | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d),"dashboards");[print(" ",x["title"]) for x in d if "Cluster" in x["title"] or "Loki" in x["title"]]'
curl -sk -u "admin:$PW" -H 'Content-Type: application/json' https://grafana.internal/api/ds/query -d '{"queries":[{"refId":"A","datasource":{"uid":"loki"},"expr":"sum(count_over_time({namespace=\"teslamate\"}[5m]))","queryType":"instant"}],"from":"now-5m","to":"now"}' | head -c 300; echo
curl -sk https://homepage.internal/api/services | python3 -c 'import json,sys;[print(g["name"],[s["name"] for s in g["services"]]) for g in json.load(sys.stdin) if g["name"]=="Monitoring"]'
```
Expected: exactly `1` Ingress for `grafana.internal`; one new Grafana pod Running and no `loki-stack-grafana` pod; `/api/health` shows `"database": "ok"` and version 13.x; datasources `Prometheus` and `Loki` (uid `loki`) both report `"status":"OK"`; about 26 dashboards including "Kubernetes / Compute Resources / Cluster" and "Loki Overview"; the Loki query returns frames with values; Homepage's Monitoring group lists Grafana.

Then hand the password to the user once: `cat $S/grafana-admin-password.txt`, and tell them it is also recoverable with `kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d`.

---

### Task 4: Repoint the Uptime Kuma TeslaMate monitor

**Files:**
- Modify: `docs/Applications/monitor-queries/teslamate-tesla-api-reachable.md`

**Interfaces:**
- Consumes: Loki at `loki.monitoring.svc.cluster.local:3100` with TeslaMate logs (Task 2).
- Produces: the monitor URL the user enters in Uptime Kuma.

- [ ] **Step 1: Prove the exact monitor query succeeds against the new Loki (Review Focus 4)**

The query covers 7 hours, so it can only succeed once the new Loki holds a TeslaMate token-refresh line. Run from inside the Uptime Kuma pod (StatefulSet pod `uptime-kuma-0`) so DNS and network match the monitor. That image has no `wget` or `curl`, so use Node's built-in `fetch`:
```bash
U='http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/query?query=sum%28count_over_time%28%7Bnamespace%3D%22teslamate%22%7D%20%7C%3D%20%22Scheduling%20token%20refresh%22%20%5B7h%5D%29%29%20%3E%200'
kubectl -n monitoring exec uptime-kuma-0 -- node -e "fetch('$U').then(r=>r.text()).then(console.log)"
```
Expected: JSON whose `result` contains a `"value"`. If `result` is `[]`, do not continue: re-run after TeslaMate's next token refresh (at most ~7h after Task 2 was deployed) and only proceed once `"value"` appears.

- [ ] **Step 2: Update the monitor documentation**

In `docs/Applications/monitor-queries/teslamate-tesla-api-reachable.md`, change the URL line from
```
http://loki-stack.monitoring.svc.cluster.local:3100/loki/api/v1/query?query=sum%28count_over_time%28%7Bnamespace%3D%22teslamate%22%7D%20%7C%3D%20%22Scheduling%20token%20refresh%22%20%5B7h%5D%29%29%20%3E%200
```
to
```
http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/query?query=sum%28count_over_time%28%7Bnamespace%3D%22teslamate%22%7D%20%7C%3D%20%22Scheduling%20token%20refresh%22%20%5B7h%5D%29%29%20%3E%200
```
Then check: `grep -rn 'loki-stack' docs/Applications/monitor-queries/` prints nothing. Also re-read the sentence "works on Loki versions that reject `or vector(0)` (ours does)" and, if Loki 3.6 accepts `or vector(0)` (test with the query above plus ` or vector(0)`), change it to say the approach is kept because the keyword check depends on an empty result, not on Loki's version.

- [ ] **Step 3: Ask the user to change the URL in Uptime Kuma**

Tell the user: open `https://monitoring.internal`, edit "Teslamate - Tesla API Reachable", replace `loki-stack.monitoring` with `loki.monitoring` in the URL, and save. Wait for their confirmation.

- [ ] **Step 4: Verify the monitor is green**

Ask the user to confirm the monitor shows UP after its next check (or trigger a check by saving). Then commit the doc:
```bash
cd /Users/chandler/Projects/flux-home-lab
git add docs/Applications/monitor-queries/teslamate-tesla-api-reachable.md
git commit -F - <<'EOF'
Point the TeslaMate API monitor at the new Loki

The monitor's query is unchanged; only the host moves from loki-stack to
loki. Verified the exact URL returns a result from inside the Uptime
Kuma pod before switching.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 5: Remove loki-stack and update docs

**Files:**
- Delete: `clusters/dev/apps/loki-stack/` (now only `helmrelease.yaml` and `kustomization.yaml`)
- Modify: `clusters/dev/apps/kustomization.yaml`
- Modify: `docs/Applications/Monitoring.md`, `docs/Applications/README.md`, `docs/Flux/README.md`
- Modify: `docs/superpowers/specs/2026-10-03-loki-modernization-design.md` (Grafana version)

**Interfaces:**
- Consumes: everything above verified.
- Produces: final state.

- [ ] **Step 1: Prove nothing else depends on loki-stack (Review Focus 1)**

Run:
```bash
cd /Users/chandler/Projects/flux-home-lab
ls clusters/dev/apps/loki-stack/
grep -rn 'loki-stack' clusters/dev --include=*.yaml | grep -v '^clusters/dev/apps/loki-stack/'
git rm -rq clusters/dev/apps/loki-stack
sed -i '' '/^  - loki-stack\/$/d' clusters/dev/apps/kustomization.yaml
kustomize build clusters/dev > $S/build-final.yaml && echo "build OK"
grep -A3 '^kind: Namespace' $S/build-final.yaml | grep -c 'name: monitoring$'
grep -c 'loki-stack' $S/build-final.yaml
```
Expected: the directory contains only `helmrelease.yaml` and `kustomization.yaml`; the reference grep prints only `clusters/dev/apps/kustomization.yaml:  - loki-stack/` (before the sed); `build OK`; the monitoring Namespace count is `1`; the final `loki-stack` count is `0`.

- [ ] **Step 2: Update the docs**

- `docs/Applications/Monitoring.md`: replace the "Loki Stack" section with a "Logging" section describing Loki 3 (single binary, retention 7d / 14d for kube-system, monitoring, teslamate, `loki.monitoring.svc.cluster.local:3100`), Alloy (DaemonSet, Promtail-compatible labels, positions on `/var/lib/alloy`), and Grafana (kube-prometheus-stack, `grafana.internal`, admin password in SealedSecret `grafana-admin`, recover with `kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d`).
- `docs/Applications/README.md`: change "Loki Stack" in both lines to "Loki, Alloy & Grafana" and the anchor to `./Monitoring.md#logging`.
- `docs/Flux/README.md`: in the directory tree replace `loki-stack/` with `alloy/` and `loki/` in alphabetical position.
- Spec: change "Grafana is on 12.x" to "Grafana is on 13.x (the version kube-prometheus-stack 91.8.2 ships)".

Check: `grep -rn -i 'loki-stack\|promtail' docs/Applications docs/Flux` prints only historical mentions (e.g. "replaced loki-stack"), none describing current state.

- [ ] **Step 3: Commit, push, reconcile**

```bash
cd /Users/chandler/Projects/flux-home-lab
git add -A clusters/dev/apps docs
git commit -F - <<'EOF'
Remove loki-stack

Loki 3, Alloy and the kube-prometheus-stack Grafana have taken over
everything it did, and the TeslaMate API monitor now queries the new
Loki. The monitoring Namespace, grafana HelmRepository and Loki
dashboard were moved out of this directory earlier, so pruning it
removes only the old Loki StatefulSet and the Promtail DaemonSet.

The old Loki PVC is not deleted by Helm (it belongs to the StatefulSet's
volumeClaimTemplate) and is removed separately.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
flux reconcile kustomization flux-system --with-source
```

- [ ] **Step 4: Verify the removal**

Run:
```bash
kubectl -n monitoring get hr
kubectl -n monitoring get pods | grep -E 'loki-stack|promtail' || echo "no loki-stack pods"
kubectl get ns monitoring
kubectl -n monitoring get hr prometheus uptime-kuma loki alloy
kubectl -n monitoring get pvc
kubectl top pods -n monitoring
```
Expected: no `loki-stack` HelmRelease or pods; Namespace `monitoring` Active with its original age; the four HelmReleases Ready; PVC `storage-loki-stack-0` still present (still Bound; Helm does not delete StatefulSet volume claims); memory per `kubectl top` is lower than the ~650 MiB loki-stack used.

- [ ] **Step 5: Delete the old Loki PVC (only after explicit user confirmation)**

Ask the user: "Delete PVC `storage-loki-stack-0` now? This is the point of no return." Only on an explicit yes:
```bash
kubectl -n monitoring delete pvc storage-loki-stack-0
kubectl -n monitoring get pvc
```
Expected: the PVC is gone; `storage-loki-0` and the Grafana and Prometheus/Alertmanager PVCs remain. Tell the user the NFS data for both old PVCs now sits in `archived-monitoring-storage-loki-stack-0-pvc-…` and `archived-monitoring-loki-stack-grafana-pvc-…` directories on the NAS, and removing them is a manual NAS task.

- [ ] **Step 6: Next-day retention check**

About 24h after Task 1: `kubectl -n monitoring logs loki-0 -c loki --since=24h | grep -i -E 'compactor|retention' | grep -i -E 'applying|marking|compact' | head`
Expected: compactor runs logged with no errors.
