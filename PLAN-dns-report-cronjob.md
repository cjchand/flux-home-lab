# Plan: Deploy dns-report CronJob

## Context

The `dns-report` repo (`ghcr.io/cjchand/generate-dns-report`) contains a Python script that queries PiHole v6's API daily for a specific client's DNS activity and posts a filtered, formatted report to Slack. GitHub Actions builds and pushes the container image to GHCR on every push to `main`. This plan covers deploying it as a K8s CronJob in this Flux-managed cluster.

The container expects these environment variables:
- `PIHOLE_URL` — PiHole address (e.g., `http://192.168.86.x`)
- `PIHOLE_PASSWORD` — PiHole application password (secret)
- `SLACK_BOT_TOKEN` — Slack bot token with `chat:write` scope (secret)
- `SLACK_CHANNEL` — Slack channel ID (non-secret)
- `CLIENT_IP` — Chromebook's static IP (non-secret)

## Cluster Patterns to Follow

Based on existing infrastructure in this repo:
- **Namespace**: `monitoring` (where Uptime Kuma, Grafana, Loki already live)
- **Secrets**: SealedSecret (existing pattern — `kubeseal` encrypts, committed to git)
- **Structure**: `clusters/dev/apps/dns-report/` (follows existing app layout)
- No persistent storage needed (stateless job)
- No ingress needed (no web UI)

## Files to Create

### `clusters/dev/apps/dns-report/kustomization.yaml`
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - cronjob.yaml
  - configmap.yaml
  - sealedsecret.yaml
```

### `clusters/dev/apps/dns-report/cronjob.yaml`
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: dns-report
  namespace: monitoring
spec:
  schedule: "0 7 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 300
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: dns-report
              image: ghcr.io/cjchand/generate-dns-report:latest
              envFrom:
                - configMapRef:
                    name: dns-report-config
                - secretRef:
                    name: dns-report-secrets
              resources:
                requests:
                  cpu: 50m
                  memory: 64Mi
                limits:
                  cpu: 200m
                  memory: 128Mi
```

### `clusters/dev/apps/dns-report/configmap.yaml`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dns-report-config
  namespace: monitoring
data:
  PIHOLE_URL: "http://192.168.86.x"     # UPDATE with PiHole RPi address
  CLIENT_IP: "192.168.86.y"              # UPDATE with Chromebook's static IP
  SLACK_CHANNEL: "C0123456789"           # UPDATE with Slack channel ID
```

### `clusters/dev/apps/dns-report/sealedsecret.yaml`
Generated via `kubeseal`. The underlying secret contains:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dns-report-secrets
  namespace: monitoring
type: Opaque
stringData:
  PIHOLE_PASSWORD: "your-pihole-app-password"
  SLACK_BOT_TOKEN: "xoxb-your-slack-bot-token"
```

To create the SealedSecret:
```bash
kubectl create secret generic dns-report-secrets \
  --namespace monitoring \
  --from-literal=PIHOLE_PASSWORD='your-pihole-app-password' \
  --from-literal=SLACK_BOT_TOKEN='xoxb-your-slack-bot-token' \
  --dry-run=client -o yaml > /tmp/dns-report-secret.yaml

kubeseal --format yaml < /tmp/dns-report-secret.yaml > clusters/dev/apps/dns-report/sealedsecret.yaml

rm /tmp/dns-report-secret.yaml
```

## Image Access

If the GHCR repo is **public**, no extra config needed. If **private**, add an `imagePullSecret`:
1. Create a GitHub PAT with `read:packages` scope
2. Create a secret and seal it:
```bash
kubectl create secret docker-registry ghcr-pull-secret \
  --namespace monitoring \
  --docker-server=ghcr.io \
  --docker-username=cjchand \
  --docker-password=YOUR_PAT \
  --dry-run=client -o yaml | kubeseal --format yaml > clusters/dev/apps/dns-report/ghcr-sealedsecret.yaml
```
3. Add `imagePullSecrets: [{name: ghcr-pull-secret}]` to the CronJob pod spec

## Implementation Steps

1. Create `clusters/dev/apps/dns-report/` directory
2. Create `kustomization.yaml`, `cronjob.yaml`, `configmap.yaml` with placeholder values
3. User fills in ConfigMap values (PiHole URL, client IP, Slack channel ID)
4. User generates SealedSecret with `kubeseal` using actual credentials
5. Commit and push — Flux syncs within 10 minutes
6. Verify deployment

## Verification

1. `kubectl get cronjob dns-report -n monitoring` — confirm it exists and shows next schedule
2. `kubectl create job --from=cronjob/dns-report dns-report-test -n monitoring` — manual trigger
3. `kubectl logs job/dns-report-test -n monitoring` — check output
4. Confirm Slack message arrives (summary in channel + full list in thread)
5. Clean up: `kubectl delete job dns-report-test -n monitoring`

## Notes

- CronJob needs network access to PiHole RPi on the LAN — works since K8s nodes share the same network
- To update the domain ignore list: push changes to the dns-report repo → GitHub Actions rebuilds the image → restart the CronJob (or wait for next run)
- Flux sync interval is 10 minutes (per `gotk-sync.yaml`)
