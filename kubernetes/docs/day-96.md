# Day 96 — Rolling Update, Failed Rollout, and Rollback

## What I Did
- Documented the `/version` addition and build/load workflow for `meeps-users-posts-api:week14-v2`, preserving existing API routes and the Day 95 image.
- Prepared the Deployment configuration: two replicas, `maxUnavailable: 0`, `maxSurge: 1`, `minReadySeconds: 10`, `progressDeadlineSeconds: 180`, and `revisionHistoryLimit: 5`.
- Prepared HTTP sampling through Traefik, revision capture, rollback, and checks against the original user/post records.
- Kept output paths directly under `kubernetes/docs/day-96-*`.

## What I Learnt
- Pod-template changes create Deployment revisions; scaling alone does not.
- Rolling updates replace Pods through ReplicaSets. Surge, readiness, and availability settings control progression but do not guarantee zero downtime.
- A rollout can stall while existing healthy replicas continue serving traffic. Kubernetes reports `ProgressDeadlineExceeded` but does not automatically roll back.
- Rollback restores a retained Pod template—not database migrations or separately managed ConfigMaps and Secrets.

## What Broke and How to Fix It
- **Planned failure:** Deploy a nonexistent image tag with `imagePullPolicy: Always` to exercise `ImagePullBackOff`; keeping `Never` would not test registry pulling.
- **Diagnosis:** Inspect Pod events, image-pull errors, and Deployment conditions; distinguish a controller progress-deadline failure from a client timeout.
- **Recovery:** Undo to the recorded healthy revision, restoring `week14-v2` and `imagePullPolicy: Never`, then reapply the healthy tracked manifest.
- **Verification:** Confirm two ready replicas, the correct `/version` response, original database records, and the saved traffic results before recording success.

**Reporting:** Claim “no failed requests observed in the monitored samples” only when the captures support it—not guaranteed zero downtime.
