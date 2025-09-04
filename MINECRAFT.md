Great — since you’re using **Flux**, the best practice is to manage your Minecraft server deployment declaratively via **Kustomize overlays** or **HelmRelease resources** (if you're using `HelmOperator` or `fluxcd/helm-controller` v2).

Here’s how to set up **a crossplay Minecraft server using GeyserMC + Floodgate** that works with both PS5 and Java PC clients — deployed entirely via **Flux**.

---

## ✅ Overview: GeyserMC + Floodgate on Kubernetes via Flux

### Features:

* Java Edition server (PaperMC)
* GeyserMC + Floodgate for Bedrock (PS5, Windows, etc.)
* Exposes:

  * `TCP 25565` (Java clients)
  * `UDP 19132` (Bedrock clients)
* Managed via `HelmRelease` or `Kustomize`

---

## 🧱 Option A: Use [itzg/minecraft-server](https://github.com/itzg/docker-minecraft-server) Helm Chart

This is the most Flux-friendly option — fully automatable, plugins supported, and battle-tested.

---

### 🧩 Step-by-Step Setup with Flux

---

### 🔹 1. Define a `HelmRepository`

```yaml
# ./clusters/production/minecraft/helmrepository.yaml
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: itzg
  namespace: minecraft
spec:
  url: https://itzg.github.io/minecraft-server-charts/
  interval: 30m
```

---

### 🔹 2. Define a `HelmRelease`

```yaml
# ./clusters/production/minecraft/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: minecraft-server
  namespace: minecraft
spec:
  interval: 5m
  chart:
    spec:
      chart: minecraft
      version: "4.15.0" # or latest
      sourceRef:
        kind: HelmRepository
        name: itzg
        namespace: minecraft
  values:
    image:
      tag: latest
    minecraftServer:
      eula: true
      type: PAPER
      version: "1.20.1"
      serviceType: LoadBalancer
      rcon:
        enabled: true
      extraPorts:
        - name: bedrock
          containerPort: 19132
          protocol: UDP
    persistence:
      enabled: true
      existingClaim: minecraft-data-pvc # or use storageClass
    resources:
      requests:
        memory: "2Gi"
        cpu: "500m"
    env:
      ENABLE_RCON: "true"
      USE_AIKAR_FLAGS: "true"
      MEMORY: "2G"
```

---

### 🔹 3. Add GeyserMC + Floodgate Plugins

Since the chart supports mounting files, you can:

1. Store `Geyser-Spigot.jar` and `Floodgate.jar` in a **GitRepository or OCI artifact**.
2. Mount the plugins using a `configMap` or `emptyDir` + init container.
3. Or: manually copy them the first time (`kubectl cp`), then persist with a PVC.

Or — easiest for now:

* Spin up the server once.
* `kubectl cp` the plugin `.jar` files into the pod.
* Restart the pod.
* The chart’s default persistence should keep the plugins across reboots.

Long-term: Automate with `kustomize` or `OCIArtifact` of your plugins dir.

---

### 🔹 4. Expose UDP 19132

The chart supports `extraPorts`, which you’ve already used above.

Make sure your cloud LoadBalancer (or MetalLB) supports UDP.

You can verify with:

```bash
kubectl get svc minecraft-server -n minecraft -o wide
```

Check that UDP 19132 is exposed correctly.

---

### 🔹 5. Add DNS Redirect to piHole

In your piHole UI:

* Go to **Local DNS > DNS Records**
* Add:

```
play.inpvp.net → <LoadBalancer IP of the Geyser server>
```

Now:

* Your **PS5** can join via the `play.inpvp.net` server tile.
* Your **son (PC)** can join using Minecraft Java at the same IP on port `25565`.

---

## 🧪 Want Me to Generate Full Manifests?

If you'd like, I can generate:

* `HelmRepository.yaml`
* `HelmRelease.yaml` with all required values
* PVC manifest
* Optional Kustomization.yaml

Just let me know:

1. Your namespace (defaulting to `minecraft` unless you say otherwise)
2. If you're using **MetalLB**, what IP range it's in (optional)
3. Whether you want **persistent storage** handled automatically or reference an existing PVC

---

This setup is clean, Flux-native, and production-hardened. Want the full YAML bundle?
