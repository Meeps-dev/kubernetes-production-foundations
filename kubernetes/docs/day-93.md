# Day 93 — Configuration, Secrets, PostgreSQL, and Migrations

> Status: Setup documented; deployment results and completion checks are not yet confirmed.

## What I Did
- Documented the database setup for `meeps-dev` in `meeps-k8s-cluster`, reusing the Day 92 namespace.
- Defined ConfigMaps, `secret.example.yaml`, and a local Secret-generation workflow with Git-ignore checks.
- Prepared PostgreSQL ClusterIP/headless Services and a StatefulSet specification with a 1 Gi PVC, probes, non-root execution, and resource budgets.
- Prepared a separate Alembic Job using `meeps-users-posts-api:k8s-baseline` and the non-superuser `meeps_migrator` role.
- Defined checks for database connectivity, migration head, required tables, and evidence capture.

## What I Learnt
- ConfigMaps hold ordinary settings; Secrets hold credentials. Base64 encoding is not encryption.
- StatefulSets provide stable Pod identities; PVCs retain storage across Pod replacement but are not backups.
- Services provide stable DNS names such as `postgres`, avoiding reliance on changing Pod IPs.
- Migration Jobs should finish independently of API replicas; a completed Job is not a continuously running service.
- PostgreSQL initialization scripts run on an empty data directory. Changing a Secret alone does not rotate an existing database password.

## What Broke and How I Fixed It
- No Day 93 error output or verified fix has been reported. No troubleshooting incident is recorded as completed.

## Verification Still to Record
- [ ] `postgres-0` is Ready and `postgres-data-postgres-0` is Bound.
- [ ] `meeps-db-migrate-day93` completes and Alembic confirms all migration heads are applied.
- [ ] `users`, `posts`, and `alembic_version` exist; `meeps_migrator` has no superuser privileges.
- [ ] The actual Secret remains untracked, and verification evidence is saved.

**Scope:** Configuration, persistent PostgreSQL, and migrations only—not API deployment.