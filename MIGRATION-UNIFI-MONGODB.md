# UniFi Controller MongoDB Migration Plan

## Current State
- Uses Bitnami MongoDB Helm chart (version 16.5.32)
- Image: bitnami/mongodb:latest (in extraInitContainers)
- Helm repository: https://charts.bitnami.com/bitnami

## Migration Deadline
August 28th, 2025 - Bitnami free tier removal

## Alternative Options
1. **Official MongoDB Community Helm Chart** - Community maintained
2. **Percona Server for MongoDB** - Enterprise-grade MongoDB alternative
3. **MongoDB Enterprise Operator** - Official enterprise operator
4. **Custom MongoDB deployment** - Using official MongoDB images

## Migration Steps
1. Research and select alternative MongoDB solution
2. Update Helm repository sources
3. Replace Bitnami container images with official MongoDB images
4. Update initialization scripts for new chart structure
5. Test deployment and data migration
6. Update sealed secrets if chart structure changes
7. Verify UniFi Controller connectivity and functionality

## Files to Modify
- `clusters/dev/apps/unifi-controller/mongodb-helm-repository.yaml`
- `clusters/dev/apps/unifi-controller/mongodb-helmrelease.yaml`
- `clusters/dev/apps/unifi-controller/mongodb-sealed-secret.yaml` (if needed)