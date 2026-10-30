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

Every monitor is attached to the Slack notifier named by --notifier (default
"#homelab-alerts (Slack)", must already exist in Kuma). Existing monitors that lack it
get it added; their other notifiers are left alone.

Pass --insecure to skip TLS verification of the Kuma URL (internal CA).

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
    # Healthy camera ingest was a steady ~36-39 Mbps until the garage camera's
    # bitrate was lowered on 2026-10-27; since then it's ~33-35 Mbps, and the
    # old 33 threshold flapped. In the 2026-10 incident the cameras' main
    # streams stalled and it sank to ~20-30 Mbps while recordings became
    # undecodable (-12909); rebooting the cameras restored it. A main stream is
    # ~3.2 Mbps, so 28 means roughly two stalled. A single dead camera is
    # Frigate Cameras Streaming's job. The 30m window smooths motion/schedule
    # swings so a brief dip doesn't alert.
    ("Synthetic - Frigate Camera Ingest Low",
     'sum(rate(container_network_receive_bytes_total{namespace="frigate",'
     'pod=~"frigate-[0-9a-f]+-[a-z0-9]+"}[30m])) * 8 / 1e6 < 28', True),
]

# Frigate's stats endpoint is JSON; jsonata evaluates to true only if no camera
# has stalled (camera_fps < 1). Catches dead RTSP streams the web UI hides.
FRIGATE_STATS = "http://frigate.frigate.svc.cluster.local:5000/api/stats"
FRIGATE_JSONATA = "$count(cameras.*[camera_fps < 1]) = 0"

NOTIFIER = "#homelab-alerts (Slack)"

INTERVAL = 60
RETRIES = 2


def wanted():
    for name, url in HTTP_MONITORS:
        yield dict(type=MonitorType.HTTP, name=name, url=url, ignoreTls=True,
                   accepted_statuscodes=["200-299", "300-399"])
    for name, host, port in TCP_MONITORS:
        yield dict(type=MonitorType.PORT, name=name, hostname=host, port=port)

    yield dict(type=MonitorType.JSON_QUERY, name="Synthetic - Frigate Cameras Streaming",
               url=FRIGATE_STATS, jsonPath=FRIGATE_JSONATA, expectedValue="true",
               jsonPathOperator="==")
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
    ap.add_argument("--notifier", default=NOTIFIER,
                    help="name of the Kuma notification to attach (default: %(default)s)")
    ap.add_argument("--insecure", action="store_true",
                    help="don't verify the Kuma server's TLS certificate")
    args = ap.parse_args()

    api = UptimeKumaApi(os.environ.get("KUMA_URL", "https://monitoring.internal"),
                       ssl_verify=not args.insecure)
    try:
        api.login(os.environ["KUMA_USER"], os.environ["KUMA_PASSWORD"])
        notifiers = {n["name"]: n["id"] for n in api.get_notifications()}
        if args.notifier not in notifiers:
            sys.exit(f"no notification named {args.notifier!r}; "
                     f"available: {', '.join(sorted(notifiers)) or '(none)'}")
        nid = notifiers[args.notifier]
        existing = {m["name"]: m for m in api.get_monitors()}
        for mon in wanted():
            # Kuma 2.x json-query monitors need a comparison operator, but the
            # client library's add_monitor can't set it, so it's applied with
            # edit_monitor (which passes extra fields through).
            operator = mon.pop("jsonPathOperator", None)
            if mon["name"] in existing:
                cur = existing[mon["name"]]
                fixes = {}
                if operator and cur.get("jsonPathOperator") != operator:
                    fixes["jsonPathOperator"] = operator
                ids = list(cur.get("notificationIDList") or [])
                if nid not in ids:
                    fixes["notificationIDList"] = ids + [nid]
                if fixes:
                    print(f"{'would fix' if args.dry_run else 'fixing  '} {mon['name']} ({', '.join(fixes)})")
                    if not args.dry_run:
                        api.edit_monitor(cur["id"], **fixes)
                else:
                    print(f"exists   {mon['name']}")
                continue
            print(f"{'would add' if args.dry_run else 'adding  '} {mon['name']}")
            if not args.dry_run:
                res = api.add_monitor(interval=INTERVAL, maxretries=RETRIES,
                                      notificationIDList=[nid], **mon)
                if operator:
                    api.edit_monitor(res["monitorID"], jsonPathOperator=operator)
    finally:
        api.disconnect()


if __name__ == "__main__":
    sys.exit(main())
