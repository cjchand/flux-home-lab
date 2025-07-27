# TeslaMate PostgreSQL Migration Plan

## Current State
- Uses Bitnami PostgreSQL Helm chart (version 16.2.1)
- Images: bitnami/postgresql:17.5.0-debian-12-r19, bitnami/postgres-exporter:0.17.1-debian-12-r13, bitnami/bitnami-shell:11-debian-11-r12
- Helm repository: https://charts.bitnami.com/bitnami

## Migration Deadline
August 28th, 2025 - Bitnami free tier removal

## Alternative Options
1. **CloudNativePG Operator** - Cloud-native PostgreSQL operator
2. **Official PostgreSQL Helm Chart** - Community maintained
3. **Zalando PostgreSQL Operator** - Production-ready operator
4. **CrunchyData PGO** - Enterprise PostgreSQL operator

## Migration Steps
1. Research and select alternative PostgreSQL solution
2. Update Helm repository sources
3. Replace container images with non-Bitnami alternatives
4. Test deployment and data migration
5. Update sealed secrets if chart structure changes
6. Verify TeslaMate connectivity and functionality

## Files to Modify
- `clusters/dev/apps/teslamate-postgres/source-helmrepo-bitnami.yaml`
- `clusters/dev/apps/teslamate-postgres/helmrelease.yaml`
- `clusters/dev/apps/teslamate-postgres/teslamate-postgres-sealed.yaml` (if needed)