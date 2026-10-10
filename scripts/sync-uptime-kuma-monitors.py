#!/usr/bin/env python3
"""Create any missing Uptime Kuma monitors for the lab's services.

Uptime Kuma keeps monitors in its database, not in Kubernetes manifests, so
Flux can't manage them. This script is the next best thing: the monitor list
lives here in git, and running it is idempotent (existing monitors, matched by
name, are left alone, so hand-tuned settings survive).

    pip install uptime-kuma-api
    export KUMA_URL=https://monitoring.internal KUMA_USER=admin KUMA_PASSWORD=...
    ./scripts/sync-uptime-kuma-monitors.py --dry-run
    ./scripts/sync-uptime-kuma-monitors.py

If the internal CA isn't trusted by your machine, set SSL_CERT_FILE (or
REQUESTS_CA_BUNDLE) to the CA cert; see scripts/generate-internal-ca.sh.
"""
import argparse
import os
import sys
from urllib.parse import quote

from uptime_kuma_api import MonitorType, UptimeKumaApi

# (name, url) - ingress hosts from clusters/dev/apps/*. Certs come from the
# internal CA, which the Kuma pod doesn't trust, so TLS errors are ignored.
HTTP_MONITORS = [
    ("Coder", "https://coder.internal"),
    ("Frigate", "https://frigate.internal"),
    ("Grafana", "https://grafana.internal"),
    ("Home Assistant", "https://homeassistant.internal"),
    ("Homepage", "https://homepage.internal"),
    ("Prometheus", "https://prometheus.internal"),
    ("Tandoor", "https://recipes.internal"),
    ("Teslamate", "https://teslamate.internal"),
    ("Teslamate Grafana", "https://teslamate-grafana.internal"),
    ("UniFi", "https://unifi.internal"),
    ("Uptime Kuma", "https://monitoring.internal"),
]

# (name, hostname, port) - things with no ingress.
TCP_MONITORS = [
    ("Mosquitto MQTT", "mosquitto.mqtt.svc.cluster.local", 1883),
    ("Loki", "loki.monitoring.svc.cluster.local", 3100),
]

PROM = "http://prometheus-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090"
PIHOLE = "192.168.86.53"

# Synthetic checks: they exercise a real code path instead of just "port open".
# Prometheus ones follow the teslamate-tesla-api-reachable pattern (see
# docs/Applications/monitor-queries/): the comparison runs in PromQL, so the
# result vector only exists when the condition holds, and an empty result has
# no `"value"` substring. `bad=True` means the query matches when something is
# WRONG, so the keyword check is inverted (monitor is down when it's found).
# (name, promql, bad)
PROM_MONITORS = [
    ("Synthetic - Scrape Targets Down", "count(up == 0) > 0", True),
    ("Synthetic - Nodes Ready",
     'sum(kube_node_status_condition{condition="Ready",status="true"}) < 3', True),
    ("Synthetic - Pods Crash Looping",
     'sum(kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}) > 0', True),
    ("Synthetic - PVC Over 90%",
     "max(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.9", True),
]

# Frigate's stats endpoint is JSON; jsonata evaluates to true only if no camera
# has stalled (camera_fps < 1). Catches dead RTSP streams the web UI hides.
FRIGATE_STATS = "http://frigate.frigate.svc.cluster.local:5000/api/stats"
FRIGATE_JSONATA = "$count(cameras.*[camera_fps < 1]) = 0"

INTERVAL = 60
RETRIES = 2


def wanted():
    for name, url in HTTP_MONITORS:
        yield dict(type=MonitorType.HTTP, name=name, url=url, ignoreTls=True,
                   accepted_statuscodes=["200-299", "300-399"])
    for name, host, port in TCP_MONITORS:
        yield dict(type=MonitorType.PORT, name=name, hostname=host, port=port)

    yield dict(type=MonitorType.JSON_QUERY, name="Synthetic - Frigate Cameras Streaming",
               url=FRIGATE_STATS, jsonPath=FRIGATE_JSONATA, expectedValue="true")
    for name, promql, bad in PROM_MONITORS:
        yield dict(type=MonitorType.KEYWORD, name=name, keyword='"value"',
                   invertKeyword=bad,
                   url=f"{PROM}/api/v1/query?query={quote(promql, safe='')}")
    # Subscribes to the broker's own $SYS topic: proves connect + subscribe +
    # delivery, not just that 1883 accepts a TCP handshake.
    yield dict(type=MonitorType.MQTT, name="Synthetic - Mosquitto Pub/Sub",
               hostname="mosquitto.mqtt.svc.cluster.local", port=1883,
               mqttTopic="$SYS/broker/version", mqttSuccessMessage="mosquitto version")
    # Resolve through Pi-hole, the same path every client uses.
    yield dict(type=MonitorType.DNS, name="Synthetic - DNS Internal (Pi-hole)",
               hostname="homepage.internal", dns_resolve_server=PIHOLE, port=53)
    yield dict(type=MonitorType.DNS, name="Synthetic - DNS External (Pi-hole)",
               hostname="example.com", dns_resolve_server=PIHOLE, port=53)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    api = UptimeKumaApi(os.environ.get("KUMA_URL", "https://monitoring.internal"))
    try:
        api.login(os.environ["KUMA_USER"], os.environ["KUMA_PASSWORD"])
        existing = {m["name"] for m in api.get_monitors()}
        for mon in wanted():
            if mon["name"] in existing:
                print(f"exists   {mon['name']}")
                continue
            print(f"{'would add' if args.dry_run else 'adding  '} {mon['name']}")
            if not args.dry_run:
                api.add_monitor(interval=INTERVAL, maxretries=RETRIES, **mon)
    finally:
        api.disconnect()


if __name__ == "__main__":
    sys.exit(main())
