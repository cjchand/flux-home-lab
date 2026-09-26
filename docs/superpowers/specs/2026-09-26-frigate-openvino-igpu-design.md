# Frigate detection on OpenVINO + Intel iGPU

**Date:** 2026-09-26
**Status:** Approved, not yet implemented
**Scope:** `clusters/dev/apps/frigate/`, `clusters/dev/cluster-services/`

## Goal

Move Frigate object detection off the raw-CPU detector onto the OpenVINO detector
running on the Intel HD 630 iGPU, and expose that iGPU to the cluster as a schedulable
resource. Success is measured as reclaimed CPU during the overnight detection window
with no regression in detection latency, skipped frames, or Home Assistant automations.

## Discovery findings

Captured 2026-09-26 against the live cluster. Several contradict the assumptions the
work started from, and the design below reflects the corrected picture.

### Deployment shape

Frigate is plain Kustomize manifests, not a HelmRelease. `config.yml` is rendered into a
ConfigMap by a `configMapGenerator`, so the generated name carries a content hash; that
hash reaches the Deployment's volume reference, meaning a config edit changes the pod
spec in Git and Flux rolls the Deployment on its own. An init container copies the
ConfigMap over `/config/config.yml` on every start, so the ConfigMap is the sole source
of truth and anything written through the Frigate UI is erased at the next restart.

### Hardware — homogeneous, all 7th gen

| Node | CPU | iGPU | `/dev/dri/renderD128` |
|---|---|---|---|
| microk8s-node-01 | i5-7500T (4C/4T) | HD 630 (`0x5912`, Kaby Lake GT2, Gen9.5) | present |
| microk8s-node-03 | i5-7500T | HD 630 | present |
| microk8s-node-04 | i5-7500T | HD 630 | present |

`i915` is loaded on all three. There are **no 6th-generation nodes**. This removes three
items the original plan budgeted for: the 6th-vs-7th-gen split, the weak-H.265-decode
caveat, and any need for a `nodeSelector` on the Frigate Deployment.

`/var/lib/kubelet` is a symlink to `/var/snap/microk8s/common/var/lib/kubelet` on every
node, so the Intel plugin's default `hostPath: /var/lib/kubelet/device-plugins` resolves
correctly with no MicroK8s-specific patch. This was the plan's largest unknown and is a
non-issue.

### Software

Frigate `0.17.2-3d4dd3a`, current — `yolo-generic` and OpenVINO GPU are both supported.
The image uses the floating `:stable` tag, so Renovate is not pinning it.

Current detector is `cpu1: {type: cpu, num_threads: 3}`. There is no `model:` block and
**no `ffmpeg.hwaccel_args` anywhere**. `config.yml` carries the comment
`# CPU-only inference — Intel GPUs on these nodes are too underpowered for Frigate`,
which this work revisits.

No GPU device plugin and no Node Feature Discovery are installed; no node advertises any
`gpu.intel.com/*` resource. cert-manager is present, so the Intel operator route would
be viable, but is not used (see Decisions).

### Cameras

All five detect inputs are Reolink `h264Preview_01_sub` substreams at 640x480 / 5 fps,
restreamed through go2rtc. **Every stream is H.264.** No camera-side codec changes are
required, and the original plan's per-camera hwaccel exclusion never triggers.

### Baseline — detection is scheduled off for most of the day

Detection is disabled 07:00–23:00 by a Home Assistant automation publishing to Frigate's
MQTT detect-switch topics. At the time of capture, all five cameras reported
`detection_enabled: false` and `detection_fps: 0.0`.

```
detectors.cpu1.inference_speed = 32.19 ms   (stale; last value before shutoff)
gpu_usages                     = None
pod                            = 1087m CPU, 3174Mi
```

That 1087m is the **detection-off floor** — go2rtc restreaming (~18% of a core alone),
five `-c:v copy` record muxers, and motion processing. It is not a detection baseline.
A meaningful before/after therefore requires forcing detection on deliberately; see
Measurement.

### Pre-existing issues found, explicitly out of scope

Recorded here so they are not lost, and to be listed as follow-ups in the PR:

1. **The doorbell has no object detection.** `camera_doorbell` is listed in the HA
   automation but has never appeared in Frigate's detect-toggle log, and its detection is
   off. Its `switch.camera_doorbell_detect` entity is most likely unavailable in HA, so
   the camera has been running motion-only.
2. **No face recognition is configured.** There is no `face_recognition:` block in
   `config.yml`, and the init container's overwrite means anything enabled through the UI
   is lost on the next restart. Face recognition is not currently running.
3. **HA automation drift.** `clusters/dev/apps/homeassistant/configmap-packages.yaml`
   specifies 22:00 on / 06:00 off. Live behaviour is 23:00 on / 07:00 off — the running
   automations were hand-pasted through the HA UI and have diverged from Git by an hour.

## Decisions

### Expose the iGPU via the Intel GPU device plugin, not hostPath

Both were evaluated. On pure engineering grounds hostPath is the proportionate choice
today: a device plugin exists to steer pods toward nodes that have the device, enforce
exclusivity between competing consumers, and make capacity visible — and with a
homogeneous three-node fleet, a single-replica Frigate, and no other GPU consumer, all
three are no-ops. The plugin also introduces a coupling that runs the wrong way, since
Frigate can currently start on any node but afterwards can only start if the plugin is
healthy.

The device plugin is chosen anyway, for two reasons that outweigh that:

- **This repository is public and read as a portfolio.** The plugin is the
  vendor-supported, documented path and reads as unambiguously correct; a raw
  `hostPath: /dev/dri` is defensible but is commonly read as a homelab shortcut. When one
  option requires a paragraph to defend and the other is self-evident at comparable cost,
  the legible one wins.
- **It is the correct end state once a second consumer exists.** If a transcoder
  (Jellyfin, Plex) is ever added, the plugin automatically keeps it and Frigate on
  different nodes, which is right for a single render engine. hostPath cannot express
  that constraint.

Verified while evaluating: there is **no** hostPath anywhere in this repository today,
and nothing would have blocked one — no Pod Security Admission labels on any namespace,
no Kyverno or Gatekeeper. The choice is not forced by policy.

### Device plugin configuration

- Vendor the manifests into `clusters/dev/cluster-services/` rather than referencing
  `github.com/intel/...?ref=` as a remote Kustomize base. A remote base would make every
  reconcile of that kustomization depend on GitHub being reachable from
  `kustomize-controller`; vendoring keeps reconciliation hermetic and matches how the rest
  of the repository is structured. A header comment records the upstream URL and tag, and
  a Renovate annotation keeps version PRs flowing.
- Pin **v0.36.0** (released 2026-05-27), not v0.37.0 (released 2026-09-16). There is no
  reason to run a ten-day-old release for this.
- Use the plain `deployments/gpu_plugin` base, **not** the `nfd_labeled_nodes` overlay.
  That overlay carries a nodeSelector on an NFD-provided label this cluster does not have,
  and the DaemonSet would schedule nowhere.
- Set `shared-dev-num: 1`, with a comment explaining why. HD 630 has a single render
  engine, so advertising more slots would advertise capacity the hardware does not have.
  Timeslicing one engine between Frigate and a transcoder is worse than scheduling them
  onto separate nodes, which is exactly what a value of 1 produces.
- Comment that non-root future consumers will need `supplementalGroups: [993]` — the
  plugin injects the device nodes but does not change their `root:render 0660` mode.
  Frigate's image runs as root, so this does not affect the work here.

### Split Phase 3 into two commits

The original plan bundled the detector switch to `device: GPU` with enabling VAAPI
decode. These have different risk profiles and different expected payoffs; landed
together, a null result is uninterpretable. They are separate commits.

## Implementation

Five commits. Commits 2 and 3 land as separate PRs with verification between them: if
`gpu.intel.com/i915` is not in node allocatable when the Deployment change reconciles,
Frigate goes `Pending` and cameras are lost until it is fixed.

| # | Change | Files | Reverts independently |
|---|---|---|---|
| 1 | `detectors.ov: {type: openvino, device: CPU}`, bundled default model | `config.yml` | yes |
| 2 | Intel GPU device plugin, vendored, pinned v0.36.0 | `cluster-services/` | yes |
| 3 | `gpu.intel.com/i915: 1` limit on the container + `device: GPU` | `deployment-frigate.yaml`, `config.yml` | yes |
| 4 | `ffmpeg.hwaccel_args: preset-vaapi` globally | `config.yml` | yes |
| 5 | YOLOv9-t at 320x320 — **gated on measurement, may not land** | `config.yml` | yes |

Commit 1 deliberately remains its own step despite looking like a formality: it is the
cheapest possible place to discover that OpenVINO will not load on this hardware at all.

Commit 5 requires exporting an ONNX model outside the repo; the binary is **not**
committed. It is placed on the Frigate config PVC at `/config/model_cache/`, with
`config.yml` referencing that path.

## Measurement

Detection runs only 23:00–07:00, so it is forced on deliberately for each measurement
rather than waiting for the overnight window. One throwaway script, kept in the session
scratchpad and not committed, run identically at each step so numbers are comparable:

1. `mosquitto_pub` detect-ON to all five cameras — including `camera_doorbell`, so it is
   represented even though HA cannot toggle it
2. Sample `/api/stats` and `kubectl top pod` every 15s for ~10 minutes
3. Report median `inference_speed`, summed `detection_fps` and `skipped_fps`, per-process
   CPU, and pod millicores
4. **Publish detect-OFF again.** The runtime override persists in Frigate's database
   across pod restarts; skipping this leaves indoor detection running until 07:00. This
   step is mandatory.

Runs are scheduled in the same wall-clock slot where practical, since activity varies.

## Verification

Per commit, beyond the metrics above:

- `detection_fps` non-zero on all five cameras and `skipped_fps` still 0
- A person event reaching Home Assistant over MQTT with unchanged topics and camera names
- Commit 2 only: `gpu.intel.com/i915` present in `kubectl describe node` allocatable on
  all three nodes
- Commit 3 only: Frigate's startup log reports OpenVINO on GPU, and `/api/stats`
  populates `gpu_usages` (currently `None`)

## Rollback

Each commit is independently revertible via `git revert` plus
`flux reconcile kustomization flux-system`. Reverting commits 3 and 2 together leaves no
residue. No persistent state is migrated at any step; the only artifact outside Git is the
optional ONNX file on the config PVC, which is inert unless `config.yml` references it.

## Expected outcome

Stated in advance so the measurements can contradict it.

HD 630 is 24 EUs. For the bundled mobiledet-class model it should comfortably match the
current 32 ms while costing close to zero CPU — **the win is offload, not latency.** The
existing "too underpowered" comment in `config.yml` is therefore half right: the iGPU is
weak for large models but adequate here.

- Commits 1–3 land and reclaim most of the detection CPU cost during the overnight window
- Commit 4 measures as noise and is dropped. The detect streams are 640x480, cheap to
  decode in software, and VAAPI carries per-stream setup and frame-copy overhead that can
  consume the gain at that resolution. The largest CPU line items in the baseline are
  go2rtc and the record muxers, neither of which hardware decode touches.
- Commit 5 measures worse than the default model on 24 EUs and is declined

The headline goal of a large round-the-clock CPU drop is not achievable, because detection
only runs eight hours a day. The realistic prize is reclaiming the detection cost within
that window.

## Principal risk

Frigate 0.17 ships a recent OpenVINO, and HD 630 is Gen9.5 — inside the supported range
but in Intel's *legacy* tier, which receives the least testing. If OpenVINO's GPU plugin
will not initialise on Gen9.5, commit 1 still succeeds on CPU and commit 3 fails loudly at
Frigate startup — a startup error, not a silent fallback. Commit 2 will already have been
installed at that point; the recovery is to revert commits 3 and 2 together, which leaves
the cluster exactly as it is today. The ordering does not avoid installing the plugin
before the GPU path is proven, but it does ensure the failure surfaces in a single
Deployment roll rather than being discovered later as degraded detection.

## Out of scope

- Moving Frigate off the cluster to dedicated hardware
- A backup NVR or camera SD-card recording
- Coral or Hailo accelerators
- The three pre-existing issues listed under Discovery
- Camera definitions, zones, masks, MQTT topics, and recording retention
