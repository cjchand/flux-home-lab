# Remote Access

Remote access is a secondary goal for this deployment. With Tailscale already in use, no additional infrastructure (public ingress, port forwarding, VPN server) is needed.

---

## Frigate UI

**Option A — Tailscale subnet routing (recommended)**

If Tailscale subnet routing is configured to advertise your cluster's pod/service CIDR, you can reach the Frigate UI directly at:

```
http://<cluster-node-ip>:<nodeport>
```

Or, if you create the optional ingress (`ingress-frigate.yaml`) and your internal DNS resolves `frigate.internal` through Tailscale, browse to:

```
https://frigate.internal
```

**Option B — kubectl port-forward**

For quick one-off access without any ingress:

```bash
kubectl port-forward -n frigate svc/frigate 8971:8971
# Then open http://localhost:8971
```

---

## go2rtc Debug UI

Useful for verifying that camera streams are healthy before trusting the Frigate UI:

```bash
kubectl port-forward -n frigate svc/frigate 1984:1984
# Then open http://localhost:1984
```

---

## Home Assistant Companion App

The HA Companion App already handles remote access via Nabu Casa (HA Cloud) or Tailscale. Once Frigate is integrated into HA (see `HOMEASSISTANT_SETUP.md`), camera feeds, snapshots, and event notifications are all accessible through the app remotely — no extra configuration needed.

---

## What Is Not Needed

- Public ingress / port forwarding — Tailscale handles the network layer
- Separate VPN — Tailscale is already present
- NodePort services — ClusterIP + port-forward or subnet routing is sufficient for a homelab

---

## Security Note

The Frigate API on port 5000 is **unauthenticated**. It is exposed only as a ClusterIP service and is not reachable from outside the cluster without an explicit tunnel (port-forward or ingress). Do not expose port 5000 to the public internet.
