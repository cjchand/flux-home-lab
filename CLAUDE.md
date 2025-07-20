# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a GitOps-managed Kubernetes home lab using Flux CD. The repository manages both cluster-wide infrastructure services and applications deployed on a microk8s cluster. The lab runs on repurposed laptops with Ubuntu and uses a dedicated NAS for persistent storage.

## Repository Structure

- `clusters/dev/` - Main Flux configuration directory (only this path is monitored by Flux)
  - `flux-system/` - Core Flux components and Git repository sync configuration
  - `cluster-services/` - Infrastructure services (NFS provisioner, Sealed Secrets)
  - `apps/` - Application deployments organized by service
- `clusters/disabled/` - Temporarily disabled configurations (outside Flux scope)
- `docs/` - Comprehensive documentation with architecture diagrams and service details

## Key Technologies

- **Flux CD**: GitOps operator managing all deployments
- **Helm**: Package manager for Kubernetes applications
- **Kustomize**: Configuration management and patching
- **Sealed Secrets**: Encrypted secret management for secure GitOps
- **Renovate**: Automated dependency updates for Helm charts

## Working with Applications

Each application lives in `clusters/dev/apps/<app-name>/` and typically contains:
- `helmrelease.yaml` - Flux HelmRelease defining the Helm chart and values
- `kustomization.yaml` - Kustomize configuration for the namespace
- `namespace.yaml` - Kubernetes namespace definition
- `source-helmrepo-*.yaml` - Helm repository sources
- Additional configs like ingress routes, secrets, or persistent volume claims

## Adding New Applications

1. Create directory under `clusters/dev/apps/<app-name>/`
2. Add Helm repository source if needed
3. Create namespace, HelmRelease, and kustomization files
4. Update `clusters/dev/apps/kustomization.yaml` to include the new app
5. For secrets, use Sealed Secrets (see docs/sealed-secrets.md)

## Managing Secrets

This repository uses Sealed Secrets for secure secret management:
- Create regular Kubernetes secrets locally (never commit)
- Encrypt with `kubeseal` using the cluster's public key
- Commit the resulting SealedSecret YAML files
- Reference encrypted secrets in HelmRelease configurations

## Development Commands

This is a declarative GitOps repository - changes are applied by committing to Git:
- Flux automatically syncs changes within 10 minutes
- Force sync: `flux reconcile kustomization flux-system`
- Check Flux status: `flux get all`
- Validate Helm releases: `flux get helmreleases -A`

## Monitoring Deployments

- Flux reconciles from the `main` branch every 10 minutes
- Applications are deployed via HelmRelease controllers
- Check deployment status in the Kubernetes cluster or through monitoring tools
- Renovate automatically creates PRs for Helm chart updates

## Architecture Notes

- Uses microk8s with Calico networking
- MetalLB provides LoadBalancer services for bare metal
- Traefik serves as ingress controller and reverse proxy
- NFS External Provisioner enables dynamic persistent volume provisioning
- All applications are namespaced and isolated