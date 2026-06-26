# Frigate NVR

Deploys Frigate NVR with a co-located Mosquitto MQTT broker in the `frigate` namespace. Streams from Reolink E1 Pro cameras via HTTP-FLV, stores recordings on the Synology NAS via NFS, and publishes events to Home Assistant.

---

## Prerequisites

- Synology NAS NFS share created and exported
- Cameras powered on and HTTP stream enabled (Reolink app → Camera Settings → Network → Advanced → HTTP)
- Camera IPs assigned (recommend DHCP reservations so they don't change)
- `kubeseal` available locally and cluster public key fetchable

---

## Step 0: Fill in Placeholder Values

Replace every placeholder before applying. Required values:

| File | Placeholder | Description |
|------|-------------|-------------|
| `pv-frigate-recordings.yaml` | `NAS_IP` | Synology NAS IP address |
| `pv-frigate-recordings.yaml` | `/NAS_NFS_PATH` | NFS export path on the NAS (e.g. `/volume1/frigate`) |
| `configmap-frigate.yaml` | `CAMERA_KITCHEN_IP` | IP address of the kitchen camera |
| `configmap-frigate.yaml` | `CAMERA_LIVING_ROOM_IP` | IP address of additional cameras (if uncommented) |
| `secret-frigate.yaml` | `Y0hBTkdFTUU=` | Base64-encoded camera password — see Step 1 |
| `deployment-frigate.yaml` | `America/Chicago` | Your timezone (TZ database name) |

---

## Step 1: Seal the Camera Password Secret

**Do not commit `secret-frigate.yaml` with a real password in plaintext.**

```bash
# Fetch the cluster's public key
kubeseal --fetch-cert \
  --controller-name=sealed-secrets \
  --controller-namespace=kube-system > pub-cert.pem

# Edit secret-frigate.yaml — replace the CAMERA_PASSWORD value with:
#   echo -n 'your-actual-password' | base64

# Seal it
kubeseal --cert=pub-cert.pem --format=yaml \
  < secret-frigate.yaml > sealed-secret-frigate.yaml

# Update kustomization.yaml: replace secret-frigate.yaml with sealed-secret-frigate.yaml
# Add secret-frigate.yaml to .gitignore
```

---

## Step 2: Deploy (Apply Order Matters)

Flux will handle ordering via the kustomization, but if applying manually:

```bash
# 1. Namespace first
kubectl apply -f clusters/dev/apps/frigate/namespace.yaml

# 2. Mosquitto (MQTT must be up before Frigate connects)
kubectl apply -f clusters/dev/apps/frigate/mosquitto/

# 3. Frigate config and secret
kubectl apply -f clusters/dev/apps/frigate/configmap-frigate.yaml
kubectl apply -f clusters/dev/apps/frigate/sealed-secret-frigate.yaml   # sealed version

# 4. Storage (PV before PVC)
kubectl apply -f clusters/dev/apps/frigate/pv-frigate-recordings.yaml
kubectl apply -f clusters/dev/apps/frigate/pvc-frigate-recordings.yaml

# 5. Frigate deployment and service
kubectl apply -f clusters/dev/apps/frigate/deployment-frigate.yaml
kubectl apply -f clusters/dev/apps/frigate/service-frigate.yaml

# 6. Optional ingress
# kubectl apply -f clusters/dev/apps/frigate/ingress-frigate.yaml
```

---

## Step 3: Verify

```bash
# All pods should be Running within ~60 seconds
kubectl get pods -n frigate

# Check Frigate logs for startup errors
kubectl logs -n frigate deployment/frigate --follow

# Verify MQTT broker is up
kubectl logs -n frigate deployment/mosquitto
```

**Verify go2rtc streams (camera connectivity):**

```bash
kubectl port-forward -n frigate svc/frigate 1984:1984
# Open http://localhost:1984 — streams should show "online"
```

**Verify Frigate UI:**

```bash
kubectl port-forward -n frigate svc/frigate 5000:5000
# Open http://localhost:5000 — cameras should appear with a live thumbnail
```

---

## Step 4: Home Assistant Integration

See `HOMEASSISTANT_SETUP.md` for MQTT integration, Frigate HACS integration, and mobile notification setup.

---

## Adding More Cameras

1. Edit `configmap-frigate.yaml`:
   - Add a new `go2rtc.streams` block for the main and sub streams
   - Add a new `cameras` block (copy from `camera_kitchen`, update name and stream paths)
2. Apply the updated ConfigMap: `kubectl apply -f clusters/dev/apps/frigate/configmap-frigate.yaml`
3. Restart Frigate: `kubectl rollout restart deployment/frigate -n frigate`

Camera names must be consistent across `go2rtc.streams` and `cameras` sections.

---

## Remote Access

See `REMOTE_ACCESS.md`.

---

## Architecture

```
Reolink E1 Pro cameras (WiFi, HTTP-FLV)
  → go2rtc (built into Frigate) via HTTP-FLV
    → Frigate (k8s Deployment, CPU inference)
      → NFS PersistentVolume → Synology NAS (recordings/clips)
      → MQTT → Mosquitto (k8s, frigate namespace)
        → Home Assistant (home-assistant namespace)
          → HA Companion App (mobile push notifications)
```
