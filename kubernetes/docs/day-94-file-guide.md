# Day 94 file guide — API Deployment and Service

These are proposed local-lab files, not evidence that a deployment has run.
No credentials are included. They do not modify application source or Day 93 files.

## Prerequisites

Use `kubernetes-production-foundations`, the session helper from Day 92,
context `kind-meeps-k8s-cluster`, and namespace `meeps-dev`.
The Day 93 database must be Ready, its PVC Bound, and migrations verified.
The validated image must be tagged `meeps-users-posts-api:k8s-v1` and loaded
into all kind nodes before applying the API Deployment.

## Files and execution order

1. Review `scripts/prepare-api-runtime.sh` and `scripts/api-runtime-grants.sql`.
2. Ensure `/.local/` is ignored by Git. Run the provisioning helper with Bash
   from the repository root. It creates a separate database role (`meeps_api`)
   and the API-only Secret (`meeps-api-credentials`).
3. The generated `.local/meeps-dev/api-secret.local.yaml` is confidential.
   Keep it untracked. The helper stops if existing state suggests a rerun;
   it does not silently rotate passwords. Recover partial state deliberately.
4. Review and validate `base/api-configmap.yaml`, `base/api-serviceaccount.yaml`,
   `base/api-deployment.yaml`, and `base/api-service.yaml` using server dry runs.
5. Apply only these four manifests. Do not apply the examples directory or
   reapply the entire base directory (which also contains the migration Job).
6. Wait for two available replicas and inspect Service EndpointSlices.
7. Port-forward the Service on loopback for manual root/health checks.
8. Run `scripts/api-smoke-test.py` in an API Pod in `create` mode against the
   Service DNS name; save stdout as `docs/evidence/day-94/fixture.json`.
9. Run `scripts/replace-one-api-pod.sh` to delete exactly one API Pod.
10. Run the smoke client in `verify` mode inside the identified replacement Pod,
    targeting `http://127.0.0.1:8000` and supplying the saved fixture JSON.
    Verify mode performs no POST requests and does not recreate records.

## Decisions and limits

- `k8s-v1` is a reserved local tag, not technically immutable. Do not move it;
  use a new tag for a new build. Use registry digests for content-addressed pins.
- Runtime grants are SELECT/INSERT on users/posts and USAGE on their sequences.
  Schema migrations continue to use the separate Day 93 migration credentials.
  New tables or write operations require additional reviewed grants.
- No Kubernetes API permissions are granted to the API ServiceAccount.
- The current /health probe checks HTTP responsiveness only. Day 95 adds the
  database-aware readiness endpoint and the remaining probe exercises.
- 128Mi/256Mi memory request/limit and 100m/500m CPU are initial lab budgets,
  not measured production sizing. Two replicas share one local machine.
- Graceful application shutdown is bounded to 20 seconds within a 30-second
  Pod termination window. This is not a zero-downtime guarantee.
- Service port-forward selects a backing Pod; it is not proof of Service data
  plane load balancing and may end when that Pod is replaced. The in-cluster
  smoke test exercises DNS and the ClusterIP Service separately.
- Pod replacement verifies API self-healing and shared database persistence,
  not PostgreSQL failover, backup recovery, or a production availability SLA.
- Keep the cluster, PostgreSQL PVC, and credentials for the next lab day.

## Sources used when preparing the files

- Kubernetes image references/pull policy: https://kubernetes.io/docs/concepts/containers/images/
- kind image import: https://kind.sigs.k8s.io/docs/user/quick-start/
- Deployments: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Security contexts: https://kubernetes.io/docs/tasks/configure-pod-container/security-context/
- Service port-forward: https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/
- Uvicorn settings: https://uvicorn.dev/settings/
- PostgreSQL 15 privileges: https://www.postgresql.org/docs/15/sql-grant.html
- Application route/schema files: Meeps-dev/kubernetes-production-foundations,
  application/app/routers/{users,posts}.py and application/app/schemas/{user,post}.py,
  fetched from the default branch for this walkthrough.
