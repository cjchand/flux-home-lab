# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a GitOps-managed Kubernetes home lab using Flux CD. The repository manages both cluster-wide infrastructure services and applications deployed on a 3-node microk8s cluster (HP EliteDesk 800 G3 mini PCs running Ubuntu 24.04). A dedicated NAS provides persistent storage.

## Repository Structure

- `clusters/dev/` - Main Flux configuration directory (only this path is monitored by Flux)
  - `flux-system/` - Core Flux components and Git repository sync configuration
  - `cluster-services/` - Infrastructure services (NFS provisioner, Sealed Secrets, cert-manager)
  - `apps/` - Application deployments organized by service
- `clusters/disabled/` - Temporarily disabled configurations (move apps here to disable without deleting)
- `docs/` - Documentation with architecture diagrams and service details

## Working with Applications

Each application lives in `clusters/dev/apps/<app-name>/` and typically contains:
- `helmrelease.yaml` - Flux HelmRelease defining the Helm chart and values
- `kustomization.yaml` - Kustomize configuration listing resources
- `namespace.yaml` - Kubernetes namespace definition
- `helm-repository.yaml` or `source-helmrepo-*.yaml` - Helm repository source

**Multi-component apps**: Complex applications (like teslamate) use a parent kustomization that references sub-components in separate directories (e.g., `teslamate-core/`, `teslamate-postgres/`, `teslamate-grafana/`).

## Adding New Applications

1. Create directory under `clusters/dev/apps/<app-name>/`
2. Add Helm repository source if the chart repo isn't already defined
3. Create namespace, HelmRelease, and kustomization files
4. Update `clusters/dev/apps/kustomization.yaml` to include the new app
5. For secrets, use Sealed Secrets (see Managing Secrets below)

## Managing Secrets

This repository uses Sealed Secrets for secure secret management:

```bash
# Fetch the cluster's public key
kubeseal --fetch-cert --controller-name=sealed-secrets --controller-namespace=kube-system > pub-cert.pem

# Encrypt a secret (create the vanilla secret locally, never commit it)
kubeseal --cert=pub-cert.pem --format=yaml < secret.yaml > sealed-secret.yaml
```

Reference encrypted secrets in HelmRelease using `existingSecret` patterns:
```yaml
auth:
  existingSecret: "my-sealed-secret"
  secretKeys:
    adminPasswordKey: "admin-password"
```

## Development Commands

This is a declarative GitOps repository - changes are applied by committing to Git:
```bash
flux reconcile kustomization flux-system   # Force immediate sync
flux get all                                # Check Flux status
flux get helmreleases -A                    # List all Helm releases
flux logs --follow                          # Stream Flux controller logs
```

## Architecture Notes

- **microk8s** cluster with Calico networking
- **MetalLB** provides LoadBalancer services for bare metal
- **Traefik** serves as ingress controller with HTTP→HTTPS redirect
- **NFS External Provisioner** enables dynamic PVs using storageClass `nfs-client`
- **cert-manager** with internal CA for TLS certificates on `.internal` domains
- **Renovate** automatically creates PRs for Helm chart version updates