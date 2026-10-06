# Day 94 — API Deployment and Service

## What I Did
- Added API Deployment, ClusterIP Service, ConfigMap, and ServiceAccount manifests for `meeps-dev`.
- Configured `meeps-users-posts-api:k8s-v1` with two replicas; observed both API Pods at `1/1 Running`.
- Specified non-root UID/GID `10001`, dropped capabilities, no privilege escalation, seccomp, a read-only root filesystem, disabled token mounting, resource budgets, and graceful termination.
- Started Service port-forwarding on `127.0.0.1:18000` and prepared user/post create-read and Pod-replacement tests.
- Standardized test output paths to `kubernetes/docs/day-94-*`, without extra documentation subfolders.

## What I Learnt
- A Deployment manages ReplicaSets, which maintain the desired number of Pods.
- Service selectors match Pod labels; EndpointSlices identify backends and their readiness.
- CPU/memory requests influence scheduling; limits constrain usage. Security contexts restrict container privileges.
- API runtime credentials should be separate from migration credentials, with real Secrets excluded from Git.
- Port-forwarding alone does not prove ClusterIP load balancing, and `/health` does not verify database access.
- Persistence testing must read the original saved user/post records after replacement—not recreate them.

## What Broke and the Fixes
- **Wrong API endpoint:** Validation attempted `localhost:8080` and failed. Correction: source `use-local-cluster.sh` and explicitly select the lab kubeconfig/context instead of disabling validation.
- **Output-path mismatch:** Commands looked for a nested `day-94/replacement-pod.txt`. Updated commands and the helper to use `kubernetes/docs/day-94-replacement-pod.txt` consistently.
- **Missing fixture:** The replacement helper stopped because `day-94-fixture.json` was missing or empty. Required fix: verify the create/read result and save the fixture before rerunning replacement; do not bypass the guard.
- **Shell warning:** `setopt BRACKETED_PASTE` was unsupported. The correction provided was to remove only that invalid option from `.zshrc`.

## Verification Status
Two running, ready API Pods were shown. Successful create/read, Pod replacement, unchanged database records, and the final verification report still require recorded results; their outputs have not been shared.

