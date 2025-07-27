# Tandoor PostgreSQL Migration Plan

## Current State
- Uses embedded Bitnami PostgreSQL subchart in Tandoor Helm release
- Configured as `postgresql.enabled: true` in values
- Helm repository: gabe565 (which includes Bitnami PostgreSQL as dependency)

## Migration Deadline
August 28th, 2025 - Bitnami free tier removal

## Alternative Options
1. **Separate PostgreSQL deployment** - Deploy PostgreSQL independently
2. **CloudNativePG Operator** - Cloud-native PostgreSQL operator
3. **External database** - Use external PostgreSQL service
4. **Update Tandoor chart** - Find version with non-Bitnami PostgreSQL

## Migration Steps
1. Research alternative PostgreSQL deployment options
2. Deploy separate PostgreSQL instance using non-Bitnami chart
3. Update Tandoor configuration to disable embedded PostgreSQL
4. Configure external database connection in Tandoor
5. Test deployment and data migration
6. Update sealed secrets for external database credentials
7. Verify Tandoor application functionality

## Files to Modify
- `clusters/dev/apps/tandoor/helmrelease.yaml`
- `clusters/dev/apps/tandoor/tandoor-postgres-sealedsecret.yaml`
- May need to add separate PostgreSQL deployment files