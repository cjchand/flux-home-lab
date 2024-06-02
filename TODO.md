# List of TODOs

* Add mDNS support
    * Example: [External mDNS](https://github.com/blake/external-mdns)
* Add Velero backups
    * Deploy MinIO as destination (off-cluster)
    * Alternatively, research S3 free tier
* Automate [`k8sviz`](https://github.com/mkimuram/k8sviz) diagrams of as-deployed state
* Monitoring
    * Add notifications
    * Move to PVC-backed storage (MicroK8s monitoring deployment uses ephemeral storage)
    * Add OS-level telemetry and monitoring
    * Consider Thanos (might be overkill)
    * Consider Loki (Lens is fine for now, but would be good from a learning aspect)
* Teslamate
    * Add PVC for Grafana (alternatively, set a default admin password as that's the main pain point)
