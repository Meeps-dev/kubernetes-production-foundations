# Security, cost and production gaps — Week 14

## Implemented design; verify against live captures

API UID/GID 10001, dropped Linux capabilities, no privilege escalation, RuntimeDefault seccomp, read-only root filesystem, bounded resource settings and writable temporary storage only. The API does not need a Kubernetes API token; the ingress and metrics controllers do, with their declared RBAC.

Administrator, migration-owner and API database roles are separate. API runtime grants support the current create/read endpoints, not arbitrary future operations. Credentials remain in ignored local files and Kubernetes Secrets. Base64 is not encryption. No encryption-at-rest deployment or external secret manager is claimed for this local cluster.

Pod Security namespace audit/warn settings do not enforce rejection. No NetworkPolicy enforcement is claimed unless a supporting CNI and actual allow/deny tests were separately implemented. Ingress is HTTP-only in the core lab. The API is a learning application, not a public authenticated/authorized product.

## Local exceptions

The API image is loaded into kind with `imagePullPolicy: Never`. A version tag is a naming convention, not registry-enforced immutability. The recorded image identity links results to a build; a production delivery process should use verified immutable artifacts.

If Metrics Server required `--kubelet-insecure-tls`, that bypass is local-testing-only. Review both the kubelet connection and the upstream APIService TLS setting; do not transfer unverified-certificate configuration to production. A raw vendor-manifest diff may show this intentional patch. Explain or reconcile that difference rather than applying a vendor file blindly.

Controller restartedAt annotations left by node maintenance can also appear in diffs. A one-off migration Job may be absent after its TTL. Neither observation justifies blanket recreation of everything in base/.

## Git and screenshots

The Day 98 audit checks the current Git index, known local credential material, private paths, Secret objects and basic private-key markers. It is not a full history scanner or a guarantee that arbitrary secrets are absent. Review staged diffs, logs, JSON captures and screenshots manually. A `.gitignore` rule does not untrack a previously committed file.

Previously exposed values must be retired/rotated in their actual system. Removing a local file does not remove historical commits, screenshot copies, remote uploads or backups. Keep any database exports outside the repository with restricted permissions.

## Reliability limits

A single database Pod and node-local volume do not provide production availability. PDBs constrain normal voluntary evictions, not direct deletions, all rollouts, HPA scale-in, host outages or insufficient replacement capacity. Four repaired canary faults show those specific conditions and recoveries; they do not establish every failure mode.

## Cost and teardown

The Week 14 runtime is local Docker/kind; no AWS deployment is part of these commands. This is not an audit of previously created AWS resources. The local costs are CPU, memory, disk, power and network usage. Teardown removes only the named cluster and listed local credentials. Image cleanup targets named Week 14 API tags without force or a global prune. Shared postgres, Traefik and kind node images are retained.

## Production improvements

Managed/resilient database, tested backup and restore, trusted TLS and metrics certificates, externally managed secrets, authentication/authorization, enforced network isolation, image provenance/scanning, capacity measurements, durable telemetry, alerting and incident runbooks require separate work.

## References

- https://kubernetes.io/docs/concepts/configuration/secret/
- https://kubernetes.io/docs/concepts/workloads/pods/disruptions/
- https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/
- https://github.com/kubernetes-sigs/metrics-server
- https://git-scm.com/docs/gitignore
