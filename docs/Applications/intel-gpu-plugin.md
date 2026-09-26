# Intel GPU Device Plugin

**Purpose**: Advertises the Intel iGPU as a schedulable Kubernetes resource

The Intel GPU device plugin runs as a DaemonSet on every node and exposes each
node's Intel integrated GPU as the extended resource `gpu.intel.com/i915`.
Workloads request it under `resources.limits` like any other resource
(`cpu`, `memory`), instead of relying on a hostPath mount of `/dev/dri` and a
privileged security context.

All three cluster nodes carry an identical Intel HD 630 (Kaby Lake, Gen9.5).

## Why vendored, not a remote base

Upstream distributes this plugin as a Kustomize base
(`deployments/gpu_plugin/base`) meant to be referenced directly from a remote
Git URL. This repo instead vendors a copy of the manifest at
`clusters/dev/cluster-services/intel-gpu-plugin.yaml`, pinned to upstream tag
`v0.36.0`, so that a Flux reconcile never depends on GitHub being reachable
from `kustomize-controller`. A vendored copy also means the exact manifest
that runs in the cluster is reviewable in this repo, not fetched at apply
time.

## Why the plain base, not `nfd_labeled_nodes`

Upstream also ships an `nfd_labeled_nodes` overlay that adds a `nodeSelector`
keyed on a label produced by Node Feature Discovery. This cluster does not run
NFD, so that overlay's DaemonSet would match zero nodes. The vendored manifest
uses the plain base instead, with only the upstream `kubernetes.io/arch: amd64`
selector.

## Why `shared-dev-num: 1`

The HD 630 has a single render engine. The plugin's `-shared-dev-num` flag
controls how many pods can be scheduled against one physical GPU
simultaneously; upstream's own default is already `1`, but this manifest sets
it explicitly in the container args because it's a real capacity decision,
not an oversight. Advertising more than one slot would let the scheduler
place two GPU workloads on the same node believing there's spare capacity,
when in fact they'd be timeslicing one render engine. Keeping the value at 1
means a second GPU consumer is instead scheduled on a different node, which
has its own idle iGPU.

## Device permissions for non-root consumers

The plugin injects the device node (`/dev/dri/renderD128`) into a requesting
pod but does not change its ownership. On these nodes the device is
`root:render 0660`. A container that does not run as root needs
`securityContext.supplementalGroups: [993]` (the `render` group's GID on
these nodes) to open it. Frigate's image runs as root, so this does not
apply there — but it will matter for any future non-root workload that
requests `gpu.intel.com/i915`.

## Upgrade path

The image tag (`intel/intel-gpu-plugin:0.36.0`) is covered by Renovate's
`kubernetes` manager, scoped to this file, so version bumps arrive as normal
PRs. A version bump PR only needs review of the tag change — it does not
touch the DaemonSet shape.

If a future upstream release changes the DaemonSet itself (new volumes,
flags, or security context fields), the tag alone isn't enough: re-vendor
the manifest from `deployments/gpu_plugin/base/intel-gpu-plugin.yaml` at the
matching upstream tag and reapply the three local changes documented at the
top of the file (namespace, `-shared-dev-num 1`, and this doc).

## Configuration Files

- **DaemonSet**: `clusters/dev/cluster-services/intel-gpu-plugin.yaml`
