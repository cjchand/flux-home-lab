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

INTERVAL = 60
RETRIES = 2


def wanted():
    for name, url in HTTP_MONITORS:
        yield dict(type=MonitorType.HTTP, name=name, url=url, ignoreTls=True,
                   accepted_statuscodes=["200-299", "300-399"])
    for name, host, port in TCP_MONITORS:
        yield dict(type=MonitorType.PORT, name=name, hostname=host, port=port)


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
