# Tandoor PostgreSQL Migration Plan

## Current State
- Uses embedded Bitnami PostgreSQL subchart in Tandoor Helm release
- Configured as `postgresql.enabled: true` in values
- Helm repository: gabe565 (which includes Bitnami PostgreSQL as dependency)

## Migration Deadline
August 28th, 2025 - Bitnami free tier removal

## Solution
Deploy separate vanilla PostgreSQL v17 using official images instead of embedded subchart

## Migration Steps
1. Create separate PostgreSQL StatefulSet using official postgres:15-alpine image
2. Create PostgreSQL Service
3. Update Tandoor configuration to disable embedded PostgreSQL
4. Configure external database connection in Tandoor
5. Create sealed secret for external database credentials

## Files Modified
- `clusters/dev/apps/tandoor/helmrelease.yaml` - Disable embedded PostgreSQL, add external config
- `clusters/dev/apps/tandoor/postgres-statefulset.yaml` - New PostgreSQL deployment
- `clusters/dev/apps/tandoor/postgres-service.yaml` - New PostgreSQL service
- `clusters/dev/apps/tandoor/tandoor-postgres-secret.yaml` - New sealed secret
- `clusters/dev/apps/tandoor/kustomization.yaml` - Include new resources