# Day 96 — Rolling update, failed rollout, and rollback

## Scope and assumptions

This implements roadmap task 83 (rolling update), with the requested failed-rollout and rollback drill. It uses the existing cluster `meeps-k8s-cluster`, namespace `meeps-dev`, Deployment `meeps-api`, Traefik host `api.meeps.local:8080`, and original Day 94 fixture. PostgreSQL, its PVC, credentials, migrations, and network routing are not modified.

The verified starting image must be `meeps-users-posts-api:k8s-v2` from Day 95. The new image is `meeps-users-posts-api:week14-v2` as requested for Day 96. These are distinct tags. Do not overwrite the old image. Version tags are a lab convention, not registry-enforced immutability.

All new captures are flat `kubernetes/docs/day-96-*` files. Run commands from the repository root. The host helper requires Python 3.9+ and the standard library only. It explicitly selects the lab kubeconfig and context on every Kubernetes call. Source `use-local-cluster.sh` in each terminal for the other commands.

## Files

- `application/app/release_info.py`: adds build-specific `GET /version`, returning `week14-v2` and the serving Pod hostname; no database I/O.
- `application/tests/test_release_info.py`: checks registration and preserves root/health contracts.
- `kubernetes/examples/day-96-rollout.patch.yaml`: strategic-merge fragment for the tracked Deployment. Not a standalone resource.
- `kubernetes/scripts/day96-verify.py`: GET-only original-user/post and release checks, run inside API Pods.
- `kubernetes/scripts/day96-lab.py`: separate `preflight`, `update`, `fail`, `rollback`, `final` checkpoints. Read before executing.

## Required manual application edit

Add to `application/app/main.py` without replacing existing code:

```python
from app.release_info import router as release_info_router
```

Alongside other router registrations:

```python
app.include_router(release_info_router)
```

Leave `/`, `/health`, `/ready`, and all user/post contracts unchanged.

## Order

1. Commit/retain Day 95 work and create the Day 96 branch.
2. Unpack these new files; run `python3 kubernetes/scripts/day96-lab.py preflight` **before editing the Deployment**.
3. Register the new route; build and test `meeps-users-posts-api:week14-v2`; load it into every kind node.
4. Apply the rollout patch **locally** to `kubernetes/base/api-deployment.yaml`, review the diff, and server-dry-run that file.
5. Watch Pods in another terminal. Run `python3 kubernetes/scripts/day96-lab.py update`; do not separately apply the Deployment beforehand.
6. Inspect the successful update and saved good revision.
7. Run `python3 kubernetes/scripts/day96-lab.py fail`; inspect its failed Pod, events, and controller condition. This intentionally leaves the faulty rollout in place.
8. Run `python3 kubernetes/scripts/day96-lab.py rollback`.
9. Run `python3 kubernetes/scripts/day96-lab.py final`; review captures before committing.

Each mutating checkpoint starts repeated host-side curl requests to `/` and `/ready` before the change, continues during it, and takes additional samples afterward. No request retries hide errors. The TSV records timestamp, path, HTTP status, duration, and curl exit status. Sampling success is not proof that all requests always succeed, nor is it a load test.

## Configuration choices

- `replicas: 2`
- RollingUpdate: `maxUnavailable: 0`, `maxSurge: 1`
- `minReadySeconds: 10`
- `progressDeadlineSeconds: 180`
- `revisionHistoryLimit: 5`
- Healthy imported images: `imagePullPolicy: Never`

A terminating Pod can remain visible while consuming resources. Surge is not a hard cap on all concurrently visible/terminating Pods, and these settings do not protect against every unrelated failure.

## Intentional failure

The helper creates **only** `kubernetes/examples/day-96-broken-deployment.yaml`, using an unpredictable nonexistent tag under `docker.io/library/python` and `imagePullPolicy: Always`. No valid new public image is expected to start. The tracked `base/api-deployment.yaml` remains healthy.

With `Never`, an absent image would not be pulled; it would not exercise the intended image-pull-backoff workflow. The helper verifies actual `ImagePullBackOff`, a missing-tag/not-found message, and `Progressing=False, reason=ProgressDeadlineExceeded`. A client timeout, registry authentication error, rate limit, or DNS failure is not accepted as equivalent missing-tag evidence.

Two good replicas should remain available while the new Pod cannot start. A failed rollout does not necessarily mean an application outage. The controller does not automatically roll back.

## Rollback and reconciliation

The actual healthy revision is saved dynamically to `day-96-good-revision.txt`. Do not assume revision 1 or 2: previous days may have produced several revisions. `rollout undo --to-revision=<saved>` restores the earlier retained Pod template, including `imagePullPolicy: Never`. The resulting revision number may be new; it need not equal the target revision number.

The helper checks the full restored Pod template, then reapplies the tracked healthy manifest to synchronize declarative/last-applied state. It verifies the release in each current API Pod, original database records, ready Service backends, and sampled HTTP traffic.

Rollback does not revert database migrations, Secrets, or ConfigMaps. This lab makes no database schema or credential changes.

## Failures and recovery

Stop at the first unexpected error. `.tmp` transcripts are incomplete, not PASS reports. Existing saved success reports are not evidence that a later failed attempt passed. Do not delete captures to force progression.

No automatic rollback runs when the helper exits. When the deliberate failure has been deployed, use the `rollback` checkpoint promptly. If the API cannot be reached before rollback, the traffic precheck intentionally refuses to call the phase a clean recovery test: restore the known-good manifest manually, record the incident, and investigate.

Emergency known-good recovery after the successful update:

```bash
cp kubernetes/docs/day-96-known-good-deployment.yaml kubernetes/base/api-deployment.yaml
kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
  --context kind-meeps-k8s-cluster -n meeps-dev \
  apply -f kubernetes/base/api-deployment.yaml
kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
  --context kind-meeps-k8s-cluster -n meeps-dev \
  rollout status deployment/meeps-api --timeout=240s
```

If the new release never completed, use `day-96-baseline-deployment.yaml` instead. Manual recovery preserves service but does not claim that the full rollback exercise passed.

Do not apply entire directory trees containing examples or snapshots. Do not delete the cluster, namespace, database Pod, PVC, retained ReplicaSets, or credentials to fix this drill.

## Main captures

- `day-96-baseline-state.json` and `day-96-baseline-deployment.yaml`
- `day-96-update-objects.txt` and `day-96-update-rollout.txt`
- `day-96-known-good-deployment.yaml` and `day-96-good-revision.txt`
- `day-96-update-traffic.tsv` and `day-96-update-traffic-summary.json`
- `day-96-failed-objects.txt`, `day-96-failed-pod-events.txt`, `day-96-failed-pod-describe.txt`
- `day-96-image-pull-backoff-pod.json` and `day-96-failed-state.json`
- `day-96-failed-rollout-traffic.tsv` and its traffic summary
- `day-96-rollback-objects.txt`, `day-96-rollback-state.json`, and rollback traffic files
- `day-96-final-verification.txt` and `day-96-final-result.json`

Inspect outputs for unintended sensitive values before sharing. Helpers never request Secret values or raw kubeconfig contents. The Git check covers `.local/` in the current index, not all historical commits.

## Source references

Implementation behavior is based on official documentation:

- Kubernetes Deployments: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Kubernetes Images: https://kubernetes.io/docs/concepts/containers/images/
- kubectl rollout undo: https://kubernetes.io/docs/reference/kubectl/generated/kubectl_rollout/kubectl_rollout_undo/
- kubectl rollout status: https://kubernetes.io/docs/reference/kubectl/generated/kubectl_rollout/kubectl_rollout_status/
- kind local image loading: https://kind.sigs.k8s.io/docs/user/quick-start/
- FastAPI router registration: https://fastapi.tiangolo.com/tutorial/bigger-applications/

The provided helper syntax and 15 offline tests were checked when preparing this package. They were not run against the user's Docker engine or Kubernetes cluster. Complete the actual checkpoints before documenting successful completion.
