# Day 95 — Liveness and Readiness Probes and North–South Infress Traffic


## What I Did
- Prepared the database-aware `/ready` endpoint: `SELECT 1` succeeds with HTTP `200`; database errors return `503` without exposing credentials.
- Defined startup/liveness checks on `/health` and readiness on `/ready`, with the rebuild/load workflow for `meeps-users-posts-api:k8s-v2`.
- Prepared version-pinned Traefik manifests, the `meeps-traefik` IngressClass, and routing from `api.meeps.local:8080` to the API.
- Prepared Ingress tests, original user/post verification, and result files directly under `kubernetes/docs/day-95-*`.

## What I Learnt
- Startup probes gate the other probes; readiness controls traffic eligibility; repeated liveness failures trigger container restarts.
- A Pod can be `Running` but unready. EndpointSlices record backend readiness without deleting the Pod.
- Ingress declares host/path rules; the controller implements them; IngressClass identifies the responsible controller.
- Liveness should not depend on PostgreSQL availability. Successful HTTP responses alone do not prove unready backends were excluded.
- Reviewed Ingress versus Gateway API; an `HTTPRoute` alone does not establish routing.

## What Broke and How to Fix It
- **Planned failure:** Point readiness to `/__day95_wrong_ready`; expect HTTP `404` and an unready new Pod while the existing healthy replicas remain available.
- **Diagnosis:** Inspect Pod events, EndpointSlice readiness, container restart counts, and Traefik backend addresses for the marked requests.
- **Recovery:** Reapply the tracked Deployment with `/ready`, wait for two ready replicas, and repeat routing and original-record checks.

## Verification Status
No Day 95 failure or recovery output has been shared. Confirm endpoint tests, traffic exclusion, recovery, and `day-95-final-verification.txt` before marking the lab complete.

**Scope:** Probes and HTTP Ingress only; TLS and a live Gateway API deployment are not included.