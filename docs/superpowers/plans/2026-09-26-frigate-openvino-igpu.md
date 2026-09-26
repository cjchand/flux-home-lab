# Frigate OpenVINO + Intel iGPU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Frigate object detection from the raw-CPU detector onto the OpenVINO detector running on the Intel HD 630 iGPU, with the iGPU exposed cluster-wide as a schedulable resource.

**Architecture:** Six sequential, independently revertible commits. Host GPU diagnostics land first via Ansible so every later step can be verified from outside the container. Then the detector swaps to OpenVINO on CPU (proving the runtime loads), the Intel GPU device plugin is vendored into `cluster-services`, and only then does Frigate request `gpu.intel.com/i915` and switch to `device: GPU`. VAAPI decode and a YOLOv9-t model follow as separately-measured, separately-revertible experiments that are expected to be declined.

**Tech Stack:** Flux CD, Kustomize, MicroK8s 1.33, Ansible, Frigate 0.17.2, Intel GPU device plugin v0.36.0, OpenVINO, VA-API.

**Spec:** `docs/superpowers/specs/2026-09-26-frigate-openvino-igpu-design.md`

## Global Constraints

- **All cluster changes go through Flux.** `kubectl` is read-only. No `apply`, `edit`, `patch`, `scale`, or `rollout restart` against Flux-managed resources. The one sanctioned `kubectl` write is `kubectl exec` into the mosquitto pod to publish MQTT (runtime state, not a Flux resource).
- **Branch:** `frigate-openvino-igpu`, already created, already holds the two spec commits.
- **One change per commit.** Tasks 3 and 4 must land as separate PRs with verification between them.
- **Do not modify:** camera definitions, zones, masks, motion masks, MQTT topics, camera names, recording or snapshot retention, or `clusters/dev/apps/homeassistant/`.
- **Do not commit model binaries.** The ONNX file in Task 6 goes on the config PVC, never into Git.
- **Frigate version:** 0.17.2-3d4dd3a. **Device plugin version:** v0.36.0 (not v0.37.0).
- **Nodes:** microk8s-node-01 (192.168.86.30), microk8s-node-03 (192.168.86.57), microk8s-node-04 (192.168.86.74). All i5-7500T / HD 630 / Gen9.5. SSH user `cjchand`, key-based, passwordless sudo is NOT available — Ansible uses `become: yes` with a sudo password prompt (`-K`).
- **Frigate currently runs on microk8s-node-04.** Confirm the node before each host-side `intel_gpu_top` check; the pod may move.
- **Detection is force-enabled via MQTT for measurement and MUST be disabled again afterwards.** The override persists in Frigate's database across pod restarts.
- **Scratchpad:** `/private/tmp/claude-501/-Users-chandler-Projects-flux-home-lab/7155e9ca-1e88-44e8-b251-e9005a8eaabb/scratchpad`. Measurement scripts and results live here and are never committed.

---

### Task 0: Ansible role for host GPU diagnostics

Installs the VA-API userspace and `intel_gpu_top` on all three nodes. No cluster resource is touched. Every later task's verification depends on this.

**Files:**
- Create: `ansible/roles/intel-gpu/tasks/main.yml`
- Create: `ansible/roles/intel-gpu/defaults/main.yml`
- Modify: `ansible/playbooks/site.yml`
- Modify: `ansible/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `vainfo`, `intel_gpu_top` on every node's `PATH`; `cjchand` in groups `render` and `video`. Later tasks invoke `ssh cjchand@<node> 'sudo intel_gpu_top -J -s 1000 -o - '` and `ssh cjchand@<node> vainfo`.

- [ ] **Step 1: Write the role defaults**

Create `ansible/roles/intel-gpu/defaults/main.yml`:

```yaml
---
# Host-side diagnostics for the Intel HD 630 iGPU.
#
# NONE of these packages are required for workloads to USE the GPU. Frigate's
# container image ships its own libva, iHD media driver and OpenVINO runtime;
# the host supplies only the i915 kernel driver and firmware, both of which are
# already present on Ubuntu 24.04 via linux-firmware.
#
# They are installed so GPU activity can be observed from OUTSIDE the container.
# Without them, "is the GPU actually busy?" can only be answered by asking the
# workload about itself, which cannot detect a silent fallback to CPU.
intel_gpu_packages:
  - intel-gpu-tools          # provides intel_gpu_top
  - vainfo                   # VA-API capability probe
  - intel-media-va-driver    # iHD driver; supports Gen9.5 (Kaby Lake)

# Users granted unprivileged access to the render/video device nodes.
# /dev/dri/renderD128 is root:render 0660, /dev/dri/card0 is root:video 0660.
intel_gpu_users:
  - cjchand
```

- [ ] **Step 2: Write the role tasks**

Create `ansible/roles/intel-gpu/tasks/main.yml`:

```yaml
---
- name: Assert the i915 kernel driver is loaded
  ansible.builtin.command: lsmod
  register: intel_gpu_lsmod
  changed_when: false

- name: Fail if i915 is missing
  ansible.builtin.fail:
    msg: >-
      i915 is not loaded on {{ inventory_hostname }}. The iGPU is unusable by
      any workload until this is resolved; check that the BIOS has not disabled
      integrated graphics.
  when: "'i915' not in intel_gpu_lsmod.stdout"

- name: Assert the render device node exists
  ansible.builtin.stat:
    path: /dev/dri/renderD128
  register: intel_gpu_render_node

- name: Fail if the render node is missing
  ansible.builtin.fail:
    msg: >-
      /dev/dri/renderD128 does not exist on {{ inventory_hostname }} even though
      i915 is loaded.
  when: not intel_gpu_render_node.stat.exists

- name: Install Intel GPU diagnostic packages
  ansible.builtin.apt:
    name: "{{ intel_gpu_packages }}"
    state: present
    update_cache: yes
    cache_valid_time: 3600

- name: Grant users access to the render and video device nodes
  ansible.builtin.user:
    name: "{{ item }}"
    groups:
      - render
      - video
    append: yes
  loop: "{{ intel_gpu_users }}"
```

- [ ] **Step 3: Wire the role into site.yml**

Modify `ansible/playbooks/site.yml` — add `intel-gpu` to the roles list, after `common`:

```yaml
---
# Full site setup - idempotent, can be run repeatedly
# Does NOT join nodes to cluster (use join-cluster.yml for that)

- name: Configure all microk8s nodes
  hosts: microk8s
  become: yes
  roles:
    - common
    - intel-gpu
    - microk8s
    - tailscale
```

- [ ] **Step 4: Run the playbook**

```bash
cd ansible && ansible-playbook playbooks/site.yml -K
```

Expected: `ok`/`changed` for the intel-gpu tasks on all three hosts, `failed=0`.

If the sudo password is not available to you, STOP and hand this step to the user — do not attempt to work around `become`.

- [ ] **Step 5: Verify the tooling works**

```bash
for h in 192.168.86.30 192.168.86.57 192.168.86.74; do
  echo "=== $h ==="
  ssh cjchand@$h 'vainfo 2>&1 | grep -E "vainfo: Driver|VAProfileH264Main.*VAEntrypointVLD" | head -3'
  ssh cjchand@$h 'which intel_gpu_top'
done
```

Expected on each node: a `vainfo: Driver version: Intel iHD driver` line, at least one `VAProfileH264Main ... VAEntrypointVLD` entry (hardware H.264 decode, which is what Task 5 depends on), and a path for `intel_gpu_top`.

Note: group membership does not apply to existing SSH sessions. If `vainfo` reports a permission error, reconnect and retry before investigating further.

- [ ] **Step 6: Document the role**

Modify `ansible/README.md` — add to the roles section, matching the existing format:

```markdown
### `intel-gpu`

Installs host-side diagnostics for the Intel HD 630 iGPU (`intel-gpu-tools`,
`vainfo`, `intel-media-va-driver`) and grants `cjchand` access to the render
and video device nodes.

These packages are **not** required for workloads to use the GPU — containers
ship their own VA-API and OpenVINO userspace. They exist so GPU activity can be
verified from outside a container, which is the only way to distinguish real
hardware acceleration from a silent software fallback.

The role also asserts that `i915` is loaded and `/dev/dri/renderD128` exists,
so it doubles as a precondition check for any GPU workload.
```

- [ ] **Step 7: Commit**

```bash
git add ansible/roles/intel-gpu ansible/playbooks/site.yml ansible/README.md
git commit -m "Add intel-gpu Ansible role for host-side GPU diagnostics

Installs intel-gpu-tools, vainfo and intel-media-va-driver on all nodes and
grants cjchand access to the render/video device nodes.

No host package is required for a container to use the iGPU — Frigate's image
ships its own libva, iHD driver and OpenVINO runtime, and the hosts already
have i915 loaded with full Kaby Lake firmware. These exist so GPU activity can
be observed from outside the container, which is the only way to tell real
acceleration from a silent CPU fallback.

Also asserts i915 is loaded and the render node exists, making the role a
precondition check for any future GPU workload.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: Measurement harness and baseline capture

No repository change and no commit. Produces the numbers every later task is judged against. Detection is currently disabled 07:00–23:00, so it must be forced on.

**Files:**
- Create: `<scratchpad>/measure.py`
- Create: `<scratchpad>/results/00-baseline.json`

**Interfaces:**
- Consumes: Task 0's host tooling (for the optional GPU column).
- Produces: `measure.py <label>`, writing `<scratchpad>/results/<label>.json` and printing a one-line summary. Every later task calls it with a different label and compares against `00-baseline`.

- [ ] **Step 1: Write the harness**

Create `<scratchpad>/measure.py`:

```python
#!/usr/bin/env python3
"""Measure Frigate detector/CPU behaviour over a window. Throwaway; not repo material.

Usage: measure.py <label> [minutes]

Forces detection ON for all cameras, samples, then forces it OFF again. The OFF
step is mandatory: Frigate persists the MQTT detect override in its database, so
skipping it leaves indoor detection running until the 07:00 HA sweep.
"""
import json
import pathlib
import statistics
import subprocess
import sys
import time

CAMERAS = [
    "camera_kitchen",
    "camera_living_room",
    "camera_workout_room",
    "camera_garage",
    "camera_doorbell",
]
RESULTS = pathlib.Path(__file__).parent / "results"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def detect(state):
    for cam in CAMERAS:
        sh(
            f"kubectl exec -n mqtt deploy/mosquitto -- "
            f"mosquitto_pub -t 'frigate/{cam}/detect/set' -m '{state}'"
        )
    print(f"detection -> {state}")


def stats():
    return json.loads(sh("kubectl exec -n frigate deploy/frigate -c frigate -- curl -s localhost:5000/api/stats"))


def pod_millicores():
    out = sh("kubectl top pod -n frigate -l app=frigate --no-headers")
    return int(out.split()[1].rstrip("m")) if out.strip() else None


def main():
    label = sys.argv[1]
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    RESULTS.mkdir(exist_ok=True)

    detect("ON")
    print("settling for 60s")
    time.sleep(60)

    samples = []
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline:
            s = stats()
            det = next(iter(s["detectors"].values()))
            samples.append(
                {
                    "t": time.time(),
                    "inference_speed": det.get("inference_speed"),
                    "detection_fps": sum(c.get("detection_fps", 0) for c in s["cameras"].values()),
                    "skipped_fps": sum(c.get("skipped_fps", 0) for c in s["cameras"].values()),
                    "enabled": [c for c, v in s["cameras"].items() if v.get("detection_enabled")],
                    "gpu_usages": s.get("gpu_usages"),
                    "full_system_cpu": float(s["cpu_usages"]["frigate.full_system"]["cpu"]),
                    "pod_millicores": pod_millicores(),
                }
            )
            print(".", end="", flush=True)
            time.sleep(15)
    finally:
        # Must run even on Ctrl-C or exception.
        detect("OFF")

    def med(key):
        vals = [x[key] for x in samples if x[key] is not None]
        return round(statistics.median(vals), 2) if vals else None

    summary = {
        "label": label,
        "samples": len(samples),
        "inference_speed_ms": med("inference_speed"),
        "detection_fps": med("detection_fps"),
        "skipped_fps": med("skipped_fps"),
        "full_system_cpu_pct": med("full_system_cpu"),
        "pod_millicores": med("pod_millicores"),
        "gpu_usages": samples[-1]["gpu_usages"] if samples else None,
        "cameras_enabled": samples[-1]["enabled"] if samples else [],
    }
    (RESULTS / f"{label}.json").write_text(json.dumps({"summary": summary, "samples": samples}, indent=2))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify MQTT control works before trusting a whole run**

```bash
kubectl exec -n mqtt deploy/mosquitto -- mosquitto_pub -t 'frigate/camera_garage/detect/set' -m 'ON'
sleep 5
kubectl exec -n frigate deploy/frigate -c frigate -- curl -s localhost:5000/api/stats \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['cameras']['camera_garage']['detection_enabled'])"
kubectl exec -n mqtt deploy/mosquitto -- mosquitto_pub -t 'frigate/camera_garage/detect/set' -m 'OFF'
```

Expected: `True`, then back off. If it prints `False`, the topic or broker path is wrong — STOP and report; do not proceed to a full run.

- [ ] **Step 3: Capture the baseline**

```bash
cd <scratchpad> && python3 measure.py 00-baseline 10
```

Expected: `cameras_enabled` lists all five, `detection_fps` > 0, `inference_speed_ms` near 32, `gpu_usages` null.

- [ ] **Step 4: Confirm detection was turned back off**

```bash
kubectl exec -n frigate deploy/frigate -c frigate -- curl -s localhost:5000/api/stats \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print({c: v['detection_enabled'] for c,v in d['cameras'].items()})"
```

Expected: every camera `False`. If any is `True`, re-publish OFF immediately. This check is repeated after every measurement in this plan and is never skipped.

- [ ] **Step 5: Report the baseline to the user and stop**

Print the summary. Do not start Task 2 until the baseline looks sane — in particular, if `detection_fps` is 0 with cameras enabled, something is wrong with the detect streams and the whole comparison would be meaningless.

---

### Task 2: Switch the detector to OpenVINO on CPU

Proves the OpenVINO runtime loads on this hardware before anything cluster-wide is installed. No device access needed.

**Files:**
- Modify: `clusters/dev/apps/frigate/config.yml:6-12`

**Interfaces:**
- Consumes: Task 1's `measure.py` and `00-baseline.json`.
- Produces: a working `detectors.ov` block that Task 4 mutates to `device: GPU`.

- [ ] **Step 1: Replace the detector block**

In `clusters/dev/apps/frigate/config.yml`, replace the existing `detectors:` block (the `cpu1` entry and its comment) with:

```yaml
detectors:
  # OpenVINO on CPU. This is a stepping stone, not the destination: it proves the
  # OpenVINO runtime loads and detects correctly on this hardware before the iGPU
  # is brought into the picture, so a later failure can be attributed cleanly.
  #
  # No model: block — Frigate's bundled default OpenVINO model is used deliberately,
  # so this commit changes exactly one variable versus the previous CPU detector.
  ov:
    type: openvino
    device: CPU
```

Leave every other key in the file untouched.

- [ ] **Step 2: Commit and let Flux reconcile**

```bash
git add clusters/dev/apps/frigate/config.yml
git commit -m "Switch Frigate detector to OpenVINO on CPU

Stepping stone before moving to the iGPU: proves the OpenVINO runtime loads
and detects on this hardware while the change is still trivially revertible
and needs no device access. Uses the bundled default model so exactly one
variable changes versus the previous cpu detector.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin frigate-openvino-igpu
flux reconcile kustomization flux-system
```

The `configMapGenerator` hash changes, so Flux rolls the Deployment automatically. Do not `kubectl rollout restart`.

- [ ] **Step 3: Verify the pod came back and OpenVINO loaded**

```bash
kubectl get pods -n frigate -l app=frigate
kubectl logs -n frigate deploy/frigate -c frigate --tail=200 | grep -iE 'openvino|detector|error' | head -20
```

Expected: pod `1/1 Running`, no OpenVINO load errors. If the log shows OpenVINO failing to initialise even on CPU, STOP — the whole approach is in question and the user needs to know before Task 3 installs anything.

- [ ] **Step 4: Measure**

```bash
cd <scratchpad> && python3 measure.py 01-openvino-cpu 10
```

Then re-run the detection-off check from Task 1 Step 4.

- [ ] **Step 5: Compare and report**

Report `inference_speed_ms`, `full_system_cpu_pct`, `pod_millicores`, and `skipped_fps` against `00-baseline`. Expect roughly comparable or slightly better inference; `skipped_fps` must not rise. Hand the numbers to the user before continuing.

---

### Task 3: Vendor the Intel GPU device plugin

Installs the plugin cluster-wide. Frigate is not touched in this task — that separation is deliberate, because a Deployment requesting a resource that does not yet exist goes `Pending` and takes the cameras down.

**Files:**
- Create: `clusters/dev/cluster-services/intel-gpu-plugin.yaml`
- Modify: `clusters/dev/cluster-services/kustomization.yaml`
- Modify: `renovate.json`
- Create: `docs/Applications/intel-gpu-plugin.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the extended resource `gpu.intel.com/i915` in node allocatable, requested by Task 4 as `resources.limits`.

- [ ] **Step 1: Create the vendored manifest**

Create `clusters/dev/cluster-services/intel-gpu-plugin.yaml`. This is the upstream
`deployments/gpu_plugin/base/intel-gpu-plugin.yaml` at v0.36.0 with three local changes,
each marked LOCAL CHANGE below:

```yaml
# Intel GPU device plugin — advertises the HD 630 iGPU as gpu.intel.com/i915.
#
# Vendored from:
#   https://github.com/intel/intel-device-plugins-for-kubernetes
#   deployments/gpu_plugin/base/intel-gpu-plugin.yaml at tag v0.36.0
#
# Vendored rather than referenced as a remote Kustomize base so that Flux
# reconciliation does not depend on GitHub being reachable from kustomize-controller.
#
# Upstream also ships a `nfd_labeled_nodes` overlay. It is deliberately NOT used:
# it carries a nodeSelector on a Node Feature Discovery label this cluster does not
# produce, so the DaemonSet would schedule nowhere.
#
# All three nodes have an identical Intel HD 630 (Kaby Lake, Gen9.5), so no node
# targeting beyond the upstream arch selector is required.
#
# renovate: datasource=docker depName=intel/intel-gpu-plugin
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: intel-gpu-plugin
  # LOCAL CHANGE: upstream sets no namespace. This repo has a single Flux
  # Kustomization with no targetNamespace, so an unqualified resource would land
  # in `default`.
  namespace: cluster-services
  labels:
    app: intel-gpu-plugin
spec:
  selector:
    matchLabels:
      app: intel-gpu-plugin
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 0
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: intel-gpu-plugin
    spec:
      containers:
      - name: intel-gpu-plugin
        env:
          - name: NODE_NAME
            valueFrom:
              fieldRef:
                fieldPath: spec.nodeName
          - name: HOST_IP
            valueFrom:
              fieldRef:
                fieldPath: status.hostIP
        image: intel/intel-gpu-plugin:0.36.0
        imagePullPolicy: IfNotPresent
        # LOCAL CHANGE: upstream passes no args, which means shared-dev-num
        # defaults to 1. Set explicitly because the value is a real decision:
        # HD 630 has a single render engine, so advertising more than one slot
        # would advertise capacity the hardware does not have. Timeslicing that
        # one engine between Frigate and, say, a transcoder is worse than having
        # the scheduler place them on different nodes — which is exactly what a
        # value of 1 produces.
        args:
          - -shared-dev-num
          - "1"
        securityContext:
          seLinuxOptions:
            type: "container_device_plugin_t"
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
          seccompProfile:
            type: RuntimeDefault
        resources:
          requests:
            memory: "45Mi"
            cpu: 40m
          limits:
            memory: "90Mi"
            cpu: 100m
        volumeMounts:
        - name: devfs
          mountPath: /dev/dri
          readOnly: true
        - name: sysfsdrm
          mountPath: /sys/class/drm
          readOnly: true
        - name: kubeletsockets
          # NOTE: /var/lib/kubelet is a symlink to
          # /var/snap/microk8s/common/var/lib/kubelet on these nodes, so the
          # upstream default path resolves correctly with no MicroK8s patch.
          mountPath: /var/lib/kubelet/device-plugins
        - name: cdipath
          mountPath: /var/run/cdi
      volumes:
      - name: devfs
        hostPath:
          path: /dev/dri
      - name: sysfsdrm
        hostPath:
          path: /sys/class/drm
      - name: kubeletsockets
        hostPath:
          path: /var/lib/kubelet/device-plugins
      - name: cdipath
        hostPath:
          path: /var/run/cdi
          type: DirectoryOrCreate
      nodeSelector:
        kubernetes.io/arch: amd64
```

Note for future consumers: the plugin injects the device nodes but does not change
their permissions. `/dev/dri/renderD128` is `root:render 0660`, so a container
running as non-root needs `securityContext.supplementalGroups: [993]`. Frigate's
image runs as root, so this does not apply in Task 4.

- [ ] **Step 2: Add it to the cluster-services kustomization**

Modify `clusters/dev/cluster-services/kustomization.yaml` — add to the end of `resources`, before the trailing `NOTE:` comment block:

```yaml
  - intel-gpu-plugin.yaml
```

- [ ] **Step 3: Extend Renovate to cover cluster-services**

Modify `renovate.json`. The current `flux` manager only scans `clusters/dev/apps/`, so the vendored plugin would never get update PRs. Replace the whole file with:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended"
  ],
  "flux": {
    "managerFilePatterns": [
      "/clusters/dev/apps/.+\\.yaml$/"
    ]
  },
  "helm-values": {
    "enabled": true
  },
  "kubernetes": {
    "managerFilePatterns": [
      "/clusters/dev/cluster-services/intel-gpu-plugin\\.yaml$/"
    ]
  },
  "packageRules": [
    {
      "matchManagers": [
        "flux",
        "helm-values"
      ],
      "matchFileNames": [
        "clusters/dev/apps/**/helmrelease.yaml"
      ]
    }
  ]
}
```

- [ ] **Step 4: Validate the kustomization builds before pushing**

```bash
kubectl kustomize clusters/dev/cluster-services | grep -A3 'kind: DaemonSet'
```

Expected: the DaemonSet renders with `namespace: cluster-services`. A build error here is much cheaper than a failed reconcile.

- [ ] **Step 5: Commit, push, reconcile**

```bash
git add clusters/dev/cluster-services/intel-gpu-plugin.yaml \
        clusters/dev/cluster-services/kustomization.yaml renovate.json
git commit -m "Add Intel GPU device plugin to cluster services

Advertises the HD 630 iGPU as gpu.intel.com/i915 so workloads can request it
as a schedulable resource rather than reaching for a hostPath /dev/dri mount.

Vendored from intel-device-plugins-for-kubernetes v0.36.0 rather than used as
a remote Kustomize base, so reconciliation does not depend on GitHub being
reachable from kustomize-controller. Uses the plain base, not the
nfd_labeled_nodes overlay, which would schedule nowhere without NFD.

shared-dev-num is pinned to 1: HD 630 has one render engine, so advertising
more would advertise capacity that does not exist, and separating GPU
consumers across nodes beats timeslicing a single engine.

Renovate's kubernetes manager is extended to cluster-services so the pinned
image still receives update PRs.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
flux reconcile kustomization flux-system
```

- [ ] **Step 6: Verify the plugin is healthy and the resource is advertised**

```bash
kubectl get ds -n cluster-services intel-gpu-plugin
kubectl logs -n cluster-services ds/intel-gpu-plugin --tail=30
for n in microk8s-node-01 microk8s-node-03 microk8s-node-04; do
  echo -n "$n: "
  kubectl get node $n -o jsonpath='{.status.allocatable.gpu\.intel\.com/i915}{"\n"}'
done
```

Expected: DaemonSet `3/3 READY`, logs showing device registration with no socket errors, and `1` allocatable on all three nodes.

If allocatable is empty, the plugin registered with the wrong kubelet socket path — report before proceeding. Task 4 must not run until all three report `1`.

- [ ] **Step 7: Document it**

Create `docs/Applications/intel-gpu-plugin.md`, following the format of the existing files in that directory. Cover: what it advertises, why vendored rather than a remote base, why the plain base and not the NFD overlay, why `shared-dev-num: 1`, the `supplementalGroups: [993]` requirement for non-root consumers, and the upgrade path (Renovate PR bumping the image tag; re-vendor the manifest from the matching upstream tag if upstream changes the DaemonSet shape).

Commit separately:

```bash
git add docs/Applications/intel-gpu-plugin.md
git commit -m "Document the Intel GPU device plugin

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 4: Frigate detection on the iGPU

**Files:**
- Modify: `clusters/dev/apps/frigate/deployment-frigate.yaml:77-85`
- Modify: `clusters/dev/apps/frigate/config.yml` (the `detectors.ov` block from Task 2)

**Interfaces:**
- Consumes: `gpu.intel.com/i915` from Task 3; `measure.py` from Task 1.
- Produces: a Frigate pod holding an i915 device, which Task 5 assumes when enabling VAAPI.

- [ ] **Step 1: Request the device in the Deployment**

In `clusters/dev/apps/frigate/deployment-frigate.yaml`, add the extended resource to the existing `resources` block. It goes under `limits` only — Kubernetes copies extended resources to `requests` automatically, and specifying both is redundant:

```yaml
          resources:
            requests:
              # Tune after observing actual usage. CPU scales with camera count and
              # resolution. Start here and adjust based on `kubectl top pod -n frigate`.
              cpu: "2"
              memory: 2Gi
            limits:
              cpu: "4"
              memory: 4Gi
              # Intel HD 630 iGPU, advertised by the intel-gpu-plugin DaemonSet in
              # cluster-services. Requesting it both grants /dev/dri access and
              # constrains Frigate to a node with a free GPU slot.
              #
              # shared-dev-num is 1 cluster-wide, so this claims the whole iGPU on
              # whichever node Frigate lands on. That is intentional: the HD 630 has
              # a single render engine and detection needs it continuously.
              #
              # Not specified under requests: Kubernetes mirrors extended resources
              # from limits automatically.
              gpu.intel.com/i915: 1
```

- [ ] **Step 2: Switch the detector to GPU**

In `clusters/dev/apps/frigate/config.yml`, change `device: CPU` to `device: GPU` in the `ov` detector, and update the comment:

```yaml
detectors:
  # OpenVINO on the Intel HD 630 iGPU. The device is granted by the
  # gpu.intel.com/i915 resource request in deployment-frigate.yaml, not by a
  # hostPath mount — see docs/Applications/intel-gpu-plugin.md.
  #
  # No model: block — Frigate's bundled default OpenVINO model.
  ov:
    type: openvino
    device: GPU
```

- [ ] **Step 3: Commit, push, reconcile**

```bash
git add clusters/dev/apps/frigate/deployment-frigate.yaml clusters/dev/apps/frigate/config.yml
git commit -m "Run Frigate detection on the Intel iGPU via OpenVINO

Requests gpu.intel.com/i915 from the device plugin and switches the OpenVINO
detector from CPU to GPU. The resource request both grants /dev/dri access and
keeps Frigate on a node with a free GPU slot.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
flux reconcile kustomization flux-system
```

- [ ] **Step 4: Verify the pod is scheduled and not Pending**

```bash
kubectl get pods -n frigate -l app=frigate -o wide
kubectl describe pod -n frigate -l app=frigate | grep -A5 -E 'Events|gpu.intel.com'
```

Expected: `1/1 Running`. If `Pending` with `Insufficient gpu.intel.com/i915`, the plugin is not advertising — revert this commit immediately (cameras are down) and re-check Task 3.

- [ ] **Step 5: Verify OpenVINO is actually on the GPU**

```bash
kubectl logs -n frigate deploy/frigate -c frigate --tail=300 | grep -iE 'openvino|gpu|device|error' | head -20
kubectl exec -n frigate deploy/frigate -c frigate -- ls -l /dev/dri
```

Expected: no OpenVINO initialisation errors, and `/dev/dri/renderD128` present inside the container.

If OpenVINO reports it cannot use the GPU and falls back, STOP. This is the Gen9.5 legacy-tier risk from the spec. Revert this commit and Task 3's, and report to the user.

- [ ] **Step 6: Measure, with an independent host-side check**

Find the node, then watch the GPU from the host while a measurement runs:

```bash
NODE=$(kubectl get pod -n frigate -l app=frigate -o jsonpath='{.items[0].spec.nodeName}')
IP=$(kubectl get node $NODE -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
echo "Frigate is on $NODE ($IP)"

# terminal A — run the measurement
cd <scratchpad> && python3 measure.py 03-openvino-gpu 10

# terminal B, while A is running — 20 seconds of engine telemetry
ssh cjchand@$IP 'timeout 20 sudo intel_gpu_top -J -s 1000 -o -' > <scratchpad>/results/03-gputop.json
```

- [ ] **Step 7: Confirm detection is off, then evaluate**

Re-run the detection-off check from Task 1 Step 4.

Then check the host telemetry:

```bash
python3 -c "
import json,re
raw = open('<scratchpad>/results/03-gputop.json').read()
busy = [float(m) for m in re.findall(r'\"Render/3D\".*?\"busy\":\s*([0-9.]+)', raw, re.S)]
print('Render/3D busy samples:', busy[:10], 'max:', max(busy) if busy else None)
"
```

**The host-side number is authoritative.** `/api/stats` reporting `gpu_usages` is Frigate describing itself and cannot rule out a silent CPU fallback. If Render/3D stays near zero while detection is running, the GPU is not doing the work regardless of what Frigate claims — report that rather than accepting the config at face value.

- [ ] **Step 8: Report the before/after**

Compare `03-openvino-gpu` against `00-baseline` and `01-openvino-cpu`: `inference_speed_ms`, `full_system_cpu_pct`, `pod_millicores`, `skipped_fps`. Hand the table to the user before starting Task 5.

---

### Task 5: VAAPI hardware decode

Expected to measure as noise and be reverted. It is a separate commit precisely so that outcome is legible.

**Files:**
- Modify: `clusters/dev/apps/frigate/config.yml` (new top-level `ffmpeg:` block)

**Interfaces:**
- Consumes: the GPU-holding pod from Task 4.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the global ffmpeg block**

In `clusters/dev/apps/frigate/config.yml`, add a top-level `ffmpeg:` block immediately after the `detectors:` block. Do not touch any per-camera `ffmpeg:` section:

```yaml
ffmpeg:
  # VAAPI, not QSV: VAAPI is the correct path for Gen9.5 integrated graphics.
  #
  # Every detect stream on this cluster is a 640x480 H.264 substream, which is
  # cheap to decode in software. VAAPI carries per-stream setup and frame-copy
  # overhead that can consume the saving at that resolution, so this is expected
  # to be roughly break-even. It is a separate commit so the measurement can say
  # so plainly, and revert cleanly if it does.
  hwaccel_args: preset-vaapi
```

- [ ] **Step 2: Commit, push, reconcile**

```bash
git add clusters/dev/apps/frigate/config.yml
git commit -m "Enable VAAPI hardware decode for Frigate

Uses the same iGPU already granted for detection. Expected to be close to
break-even: all detect streams are 640x480 H.264, cheap in software, and VAAPI
adds per-stream setup and frame-copy overhead at that size. Landed separately
so the measurement can be read on its own and reverted without touching the
detector.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
flux reconcile kustomization flux-system
```

- [ ] **Step 3: Check for decode errors before measuring**

```bash
kubectl logs -n frigate deploy/frigate -c frigate --tail=200 | grep -iE 'vaapi|hwaccel|ffmpeg.*error' | head -20
```

Expected: no repeated ffmpeg errors. Frigate falls back to software decode silently on VAAPI failure, so an absence of errors is not proof it worked — Step 4 is.

- [ ] **Step 4: Measure, with the Video engine check**

```bash
NODE=$(kubectl get pod -n frigate -l app=frigate -o jsonpath='{.items[0].spec.nodeName}')
IP=$(kubectl get node $NODE -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')

cd <scratchpad> && python3 measure.py 04-vaapi 10
# concurrently:
ssh cjchand@$IP 'timeout 20 sudo intel_gpu_top -J -s 1000 -o -' > <scratchpad>/results/04-gputop.json
```

Re-run the detection-off check from Task 1 Step 4.

```bash
python3 -c "
import json,re
raw = open('<scratchpad>/results/04-gputop.json').read()
vid = [float(m) for m in re.findall(r'\"Video\".*?\"busy\":\s*([0-9.]+)', raw, re.S)]
print('Video engine busy samples:', vid[:10], 'max:', max(vid) if vid else None)
"
```

**If the Video engine stays idle, VAAPI is not engaged** — ffmpeg is soft-decoding regardless of the config. Revert this commit; do not leave config in the repo that claims an acceleration it is not getting.

- [ ] **Step 5: Decide**

Keep the commit only if `full_system_cpu_pct` or `pod_millicores` improved measurably against `03-openvino-gpu` **and** the Video engine showed activity. Otherwise `git revert` it and record the measurement in the PR description as the reason. A reverted commit with a documented number is a better outcome than a kept commit with no evidence.

---

### Task 6: YOLOv9-t 320 (gated — expected to be declined)

Do not start this task without explicitly confirming with the user, using Task 4's numbers. The spec predicts this will measure worse than the bundled model on 24 EUs.

**Files:**
- Modify: `clusters/dev/apps/frigate/config.yml` (add a `model:` block)
- Create (NOT in Git): `/config/model_cache/yolov9-t-320.onnx` on the Frigate config PVC

**Interfaces:**
- Consumes: the GPU detector from Task 4.
- Produces: nothing.

- [ ] **Step 1: Check there is headroom to justify this**

From `03-openvino-gpu`: if `inference_speed_ms` is already close to the per-frame budget, a larger model cannot fit. The budget is 5 cameras x 5 fps = 25 inferences/sec, i.e. 40ms per inference if fully saturated. Report the margin to the user and get an explicit go-ahead.

- [ ] **Step 2: Export the model**

Per Frigate's documented export path (https://docs.frigate.video/configuration/object_detectors, OpenVINO -> YOLOv9), with `MODEL_SIZE=t IMG_SIZE=320`. Run it locally; the output is a single `.onnx` file. Report its path and size to the user.

- [ ] **Step 3: Get the file onto the config PVC**

The binary must not be committed. Ask the user to place it at `/config/model_cache/yolov9-t-320.onnx` on the Frigate config PVC — the repository has no mechanism for shipping binaries, and `kubectl cp` into a Flux-managed pod is a write this plan's constraints do not permit.

- [ ] **Step 4: Add the model block**

In `clusters/dev/apps/frigate/config.yml`, after the `detectors:` block:

```yaml
model:
  # NOTE: the .onnx file is NOT in this repository. It lives on the Frigate config
  # PVC at the path below. If the PVC is ever rebuilt, this block must be removed
  # or the model re-exported, or Frigate will fail to start.
  model_type: yolo-generic
  width: 320
  height: 320
  input_tensor: nchw
  input_dtype: float
  path: /config/model_cache/yolov9-t-320.onnx
  labelmap_path: /labelmap/coco-80.txt
```

- [ ] **Step 5: Commit, push, reconcile, measure**

```bash
git add clusters/dev/apps/frigate/config.yml
git commit -m "Try YOLOv9-t 320 as the OpenVINO model

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
flux reconcile kustomization flux-system
cd <scratchpad> && python3 measure.py 05-yolov9t 10
```

Re-run the detection-off check from Task 1 Step 4.

- [ ] **Step 6: Decide**

Keep only if `inference_speed_ms` is acceptable **and** `skipped_fps` stayed at 0. Any skipped detections mean the model is too heavy for this iGPU — revert. Do not suggest moving up to `s`.

---

### Task 7: Open the pull request

- [ ] **Step 1: Confirm the final state is clean**

```bash
git log --oneline main..frigate-openvino-igpu
kubectl get pods -n frigate -l app=frigate
kubectl exec -n frigate deploy/frigate -c frigate -- curl -s localhost:5000/api/stats \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print({c: v['detection_enabled'] for c,v in d['cameras'].items()})"
```

Detection must be `False` everywhere — the HA schedule owns it, not us.

- [ ] **Step 2: Verify Home Assistant still works**

Confirm with the user that person detection events still reach HA and any person/face automations still fire. This cannot be checked from the cluster alone, and it is the acceptance criterion that matters most.

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "Move Frigate detection to OpenVINO on the Intel iGPU" --body "..."
```

The body must contain:
- The before/after table: `inference_speed_ms`, `full_system_cpu_pct`, `pod_millicores`, `skipped_fps` for baseline / openvino-cpu / openvino-gpu, plus vaapi and yolov9 if kept.
- Which optional commits were reverted and the measurement that justified it.
- The honest scope note: detection runs only 23:00–07:00, so the CPU saving applies within that window, not around the clock.
- The three out-of-scope follow-ups from the spec: doorbell detection disabled, no face recognition configured, HA automation drift (22:00/06:00 in Git vs 23:00/07:00 live).
- A link to the spec.

End the body with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
