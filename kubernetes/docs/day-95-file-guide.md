# Day 95 — File guide

These proposed files extend the existing lab. They contain no real credentials or prewritten PASS evidence.

## Application
- `application/app/readiness.py`: database-aware `/ready` using the existing `DATABASE_URL`.
- `application/tests/test_readiness.py`: offline tests with mocked DB access.
- **Manual integration:** in `application/app/main.py`, add `from app.readiness import router as readiness_router`, then `app.include_router(readiness_router)`. Preserve existing routes.

## Manifests
- `kubernetes/examples/day-95-api-probes.patch.yaml`: strategic-merge patch to update the tracked API Deployment locally; not a standalone resource.
- `kubernetes/cluster/ingress-controller/namespace.yaml`: Traefik namespace.
- `kubernetes/cluster/ingress-controller/rbac.yaml`: service account, scoped RBAC, IngressClass.
- `kubernetes/cluster/ingress-controller/traefik-deployment.yaml`: version-pinned controller; resolve its image to a registry digest before applying.
- `kubernetes/cluster/ingress-controller/traefik-service.yaml`: NodePorts 30080/30443 matching the existing kind mappings.
- `kubernetes/base/ingress.yaml`: HTTP route for `api.meeps.local` and `/` to `meeps-api:80`.
- `kubernetes/examples/day-95-httproute.example.yaml`: optional Gateway API equivalent, reference only.

## Helpers
- `day95-test-ingress.py`: GET-only tests through Traefik including original Day 94 user/post records.
- `day95-readiness-drill.sh`: breaks only the live readiness path; records an unready Pod, events, endpoints and twenty HTTP requests; verifies backend logs; restores the tracked manifest. Run from the repository root after working Day 95 deployment and ingress.
- `day95-check-access.py`: rejects missing/incorrect access logs, non-200 responses, or any backend other than the ready IPs. The non-secret `X-Meeps-Drill` header is logged for correlation; other request headers are dropped.
- `day95-final-check.sh`: fresh health, probe, workload, routing, original-record and Git-index checks. Publishes the final report only on success.

## Output layout
All result files go directly under `kubernetes/docs/`, named `day-95-*`. No evidence subfolders.

## Safety
- Review helpers before running them. Finish Day 94 first and retain `day-94-fixture.json` plus the database PVC.
- The drill's exit trap attempts restoration on ordinary errors/interrupts. A killed shell, disconnected runtime, or unavailable API server can prevent recovery.
- Manual recovery: source the session helper; apply `kubernetes/base/api-deployment.yaml`; wait for `deployment/meeps-api` rollout.
- Do not edit the tracked good readiness path during the drill. Do not recreate test records to claim persistence.
- A successful traffic sample does not guarantee zero downtime, production HA, or database backup recovery.

## Validation scope
The supplied YAML and shell/Python syntax were checked offline, and isolated mocked readiness tests were exercised. The actual Docker image, cluster admission, resources, network routing and fault drill must be tested on the user's machine. Generating this package did not modify a live cluster.
