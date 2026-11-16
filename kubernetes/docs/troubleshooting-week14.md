# Week 14 — Troubleshooting and Recovery Notes

This document records the actual setup and operating problems encountered while moving the Meeps API to local Kubernetes, alongside the controlled failure exercises provided for Days 95–98.

**Status discipline:** a diagnosed problem, a proposed correction, and a verified recovery are different things. The Day 97 drain remains deferred. Day 98 verification is independent of it. No section below substitutes a document or a prepared script for a successful runtime result.

## Environment and diagnostic starting point

- Cluster: `meeps-k8s-cluster`.
- Context: `kind-meeps-k8s-cluster`.
- Application namespace: `meeps-dev`.
- Controller namespaces: `traefik-system` and `kube-system`.
- Main workload: `Deployment/meeps-api`.
- Database: `StatefulSet/postgres`, PVC `postgres-data-postgres-0`.
- Outputs: flat files directly under `kubernetes/docs/day-NN-*`.

Before investigating in a new terminal:

```bash
cd "$HOME/kubernetes-production-foundations"
source kubernetes/scripts/use-local-cluster.sh
kubectl config current-context
```

Do not reset the cluster, delete the database PVC, rotate credentials, remove probes, or bypass validation to conceal a failure. Inspect the smallest relevant scope first.

## 1. Day 92 — kind installation failed before download

**Initial symptom**

```text
mkdir: /Users/user/.local/share: Permission denied
```

**First diagnostic:** inspect the failed installer line, then run `command -v kind`. The failure occurred while creating its destination directory, before downloading the binary.

**Root cause:** the chosen installation directory was not writable. This was not established as a binary-compatibility failure. The Kustomize version shown by `kubectl version --client` was embedded manifest tooling, not a replacement for kind.

**Correction:** install the Intel macOS kind binary into `~/meeps-tools/bin`, verify its published checksum, and use that path in `use-local-cluster.sh`.

```bash
export PATH="$HOME/meeps-tools/bin:$PATH"
hash -r
command -v kind
kind version
```

**Observed result:** checksum validation passed and kind resolved to the new directory.

**Preventive control:** test destination permissions, select the correct architecture, verify downloads, and keep the installed path consistent with the session helper. Do not use broad permission changes or `sudo` as the first response.

## 2. Day 94 — validation targeted localhost:8080

**Initial symptom**

```text
failed to download openapi:
Get "http://localhost:8080/openapi/v2?timeout=32s": EOF
```

**First diagnostic**

```bash
printf 'KUBECONFIG=%s\n' "${KUBECONFIG:-NOT_SET}"
kubectl config current-context
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}{"\n"}'
```

**Diagnosis:** the command was targeting the wrong connection configuration, before it could establish whether the manifests were valid. The lab uses a dedicated kubeconfig outside the repository.

**Correction:** source the session helper and select `kind-meeps-k8s-cluster` using `~/.kube/meeps-k8s-cluster.yaml`; confirm node connectivity before retrying validation. Later captures showed the API running, but the original screenshot alone did not certify the connection repair.

**Preventive control:** select context/kubeconfig explicitly for risky operations. Do not use `--validate=false` to repair a network or kubeconfig problem.

A later `https://127.0.0.1:<assigned-port>: connection refused` is a different symptom: the correct endpoint may be temporarily unavailable. Inspect Docker's existing node containers and API availability rather than inventing another port or creating a new cluster.

## 3. Day 94 — missing fixture and inconsistent output paths

**Initial symptoms**

```text
cat: kubernetes/docs/day-94/replacement-pod.txt: No such file or directory
STOP: First save a successful create/read fixture.
```

**First diagnostic**

```bash
ls -l kubernetes/docs/day-94-fixture.json \
      kubernetes/docs/day-94-fixture.tmp \
      kubernetes/docs/day-94-replacement-pod.txt
```

Missing-file errors are useful here; do not create empty placeholders to remove them.

**Root cause:** earlier commands used nested paths, while the repository used flat `day-94-*` filenames. The replacement helper also required a verified original-record fixture that had not been saved at its expected final path.

**Correction:** align commands and `replace-one-api-pod.sh` to `kubernetes/docs/day-94-*`. Complete the create/read check, verify any existing temporary result, and save `day-94-fixture.json` before replacing a Pod. Only a successful replacement writes `day-94-replacement-pod.txt`.

**Recovery proof:** the replacement Pod must read the original user/post IDs in verify mode. Recreating records is not proof that the database data survived the API replacement.

**Preventive control:** use one output-path convention, preserve fixtures, and stop a destructive test when its prerequisites are missing. The guard prevented premature Pod deletion.

## 4. Day 94 — editor and shell warnings were separate issues

The shell warning `setopt: no such option: BRACKETED_PASTE` came from `.zshrc`, not Kubernetes. The correction was to back up `.zshrc` and remove only that unsupported option.

Later, VS Code reported `Import "yaml" could not be resolved` while the terminal successfully executed the Day 98 helper and its tests. The terminal used `day98-tools`; the editor showed a different `.venv` interpreter.

**Correction:** select `.local/day98-tools/bin/python` in VS Code for the validation helper. Do not install helper dependencies into the application environment solely to hide an editor-interpreter mismatch.

**Preventive control:** separate editor diagnostics, shell startup warnings, command execution errors, and cluster failures instead of treating every warning as the same incident.

## 5. Day 97 — HPA handoff rejected four healthy replicas

**Initial symptom**

```text
STOP: Need two healthy replicas before ownership handoff.
```

**First diagnostic:** inspect live desired, updated, ready, and available replica counts—not just the YAML file.

**Relevant observation**

```text
DESIRED  UPDATED  READY  AVAILABLE
4        4        4      4
```

All three nodes were ready, PostgreSQL was running, its PVC was bound, and no HPA existed. Historical restart/readiness warnings did not change that current four-ready-Pod result.

**Root cause:** the lab helper required a settled two-replica baseline. This was a helper prerequisite, not a general Kubernetes restriction on creating an HPA.

**Correction used in the workflow:** before HPA creation, return to two with `day97-lab.py manual 2`, verify the settled count, then run `handoff`. The handoff updates last-applied ownership and removes the fixed count from the tracked manifest.

**Observed later state:** HPA existed with range 2–5, numeric CPU utilization, and two replicas. The normal PDB allowed one disruption.

**Preventive control:** distinguish configured counts from live counts. Do not repeat the manual-scaling correction after HPA owns the Deployment; do not reapply historical manifests with `spec.replicas`.

## 6. Day 97 — Metrics Server could not relocate from a cordoned worker

**Initial symptom**

```text
Waiting for deployment "metrics-server" rollout to finish:
1 old replicas are pending termination...
error: timed out waiting for the condition
```

**First diagnostics**

```bash
kubectl -n kube-system get replicasets,pods -l k8s-app=metrics-server -o wide
kubectl -n kube-system describe pods -l k8s-app=metrics-server
kubectl -n kube-system get deployment metrics-server \
  -o jsonpath='{.spec.template.spec.nodeSelector}{"\n"}'
```

**Relevant evidence:** the Deployment required `kubernetes.io/hostname: meeps-k8s-cluster-worker2`. Scheduler events reported a node-selector mismatch, untolerated taints, and an unschedulable node. The replacement later scheduled onto `worker2` after cleanup uncordoned it.

**Confirmed root cause:** the helper cordoned the exact node required by a hard hostname selector. The replacement could not move to a different eligible worker.

**Correction:** remove only Metrics Server's hostname restriction, retain the Linux selector, and correct the saved manifest if it contains the same pin. This is unrelated to the API's `kubernetes.io/hostname` topology-spread key, which should not be removed.

**Observed follow-up:** resource metrics were available again. A later drain attempt passed beyond Metrics Server relocation and stopped at Traefik instead. That is not evidence of a completed node drain.

**Preventive control:** review selectors, affinity, taints, and capacity before maintenance. Increasing the timeout cannot solve a contradictory hard placement requirement. The rollout message alone does not prove an old Pod is stuck terminating; inspect actual deletion timestamps and the replacement Pod's events.

## 7. Day 97 — Traefik relocation timed out; maintenance deferred

**Initial symptom:** after cordoning `worker2`, the helper restarted Traefik and timed out waiting for its rollout. Cleanup reapplied the normal PDB and uncordoned the worker.

**First diagnostic**

```bash
kubectl -n traefik-system get deployment,replicaset,pods -o wide
kubectl -n traefik-system describe deployment traefik
kubectl -n traefik-system get events --sort-by=.metadata.creationTimestamp
```

**Root-cause boundary:** the timeout is confirmed; its underlying scheduling or readiness cause was not established in the supplied evidence. Traefik's inspected `nodeSelector` was empty, so the Metrics Server hostname diagnosis must not be copied to Traefik.

**Disposition:** stop retrying the maintenance exercise. Preserve the failed transcript and mark the drain `DEFERRED_NOT_VERIFIED`. Do not force-delete controllers, bypass eviction safeguards, or claim PDB/drain success.

**Preventive control:** separate controller-relocation assumptions from an application PDB exercise. Independent lab exercises should not require repeated disruptive operations merely to generate an expected report filename.

## 8. Day 98 — a completion-file dependency blocked independent work

**Initial symptoms**

```text
STOP: First finish Day 97 and run day97-lab.py final.
STOP: Missing checkpoint: kubernetes/docs/day-98-baseline.json
STOP: Missing checkpoint: kubernetes/docs/day-97-drain-result.json
```

**Diagnosis:** `final` reads completed results; it does not perform the missing operation. Failed drain attempts never reached the code that writes the result, so rerunning `final` could not create it. Day 98 setup also lacked a baseline because its preflight stopped first.

**Root cause:** the supplied Day 98 helper unnecessarily required the entire Day 97 completion report before independent canary fault tests.

**Correction:** patch only that completion-file dependency. Retain cluster identity, live API/database/HPA/PDB health, original-record checks, private-file handling, and canary isolation. Record the drain as `DEFERRED_NOT_VERIFIED` rather than fabricate a success file.

**Observed follow-up:** execution progressed to Day 98 manifest validation. The old drain dependency is not a valid reason to resume Day 97 retries.

**Preventive control:** use live prerequisites relevant to the operation; distinguish a missing report from a failed production resource. Never manufacture a PASS JSON file to satisfy a guard.

## 9. Day 98 — Metrics Server patch rendered in the wrong namespace

**Initial symptom**

```text
the namespace from the provided object "kube-system"
does not match the namespace "meeps-dev"
```

**First diagnostic:** locate the failing file and the helper's `rendered_patch()` call. The failure affected `kubernetes/cluster/metrics-server/kind-local-tls.patch.json`; other resources had already passed their dry-run stages.

**Root cause:** the helper rendered the Metrics Server Deployment using its default application namespace instead of the target object's namespace. This was a bug in the supplied validation helper, not a requirement to move Metrics Server or change the application namespace.

**Correction to the local rendering call**

```python
pch = k(
    'patch', '--local', '--type=' + typ,
    '-f', '-', '-p', json.dumps(doc), '-o', 'json',
    data=json.dumps(baseline),
    ns=baseline.get('metadata', {}).get('namespace', NS),
)
```

Keep the earlier drain-dependency repair intact. Back up the helper before editing and rerun its tests and `validate`. No node drain, controller restart, Secret change, or repetition of the canary faults is needed for this local repair.

**Recovery proof:** the patch is rendered successfully and the new validation inventory reports PASS for its declared scope. The pre-fix inventory remains a failed run, not evidence of final success.

**Preventive control:** test multi-namespace rendering explicitly. A local-only kubectl operation can still enforce namespace consistency on its input object.

## 10. Day 98 — diff exit 1 was not the validation error

The validation summary reported differences for:

```text
ConfigMap/meeps-db-init
Job/meeps-db-migrate-day93
Deployment/metrics-server
```

**First diagnostic**

```bash
less kubernetes/docs/day-98-manifest-diff.txt
```

For `kubectl diff`, exit `0` means no differences, `1` means differences exist, and values greater than `1` indicate an error.

**Disposition:** inspect the actual fields and record a decision in `day-98-diff-review.md`. The summary alone does not establish that the database ConfigMap drift, Job difference, or Metrics Server difference is acceptable.

A TTL-cleaned Job, restart annotation, or documented local TLS patch can explain some differences, but those are hypotheses until the actual diff supports them. Do not rerun migrations, modify an initialized database, or overwrite controller settings solely to make the diff empty.

**Preventive control:** separate syntax/admission validation, desired/live differences, and runtime testing. Do not blanket-apply a tree containing examples and snapshots.

## 11. Controlled Day 98 fault catalogue

The test workload is `meeps-day98-canary`, with its own labels and Service. Main API Ingress/HPA/PDB selectors do not target it. The catalogue below describes the supplied tests; completed observations belong in the generated reports.

| Scenario | Initial symptom and focused diagnostic | Root cause and correct recovery | Preventive control |
|---|---|---|---|
| `readiness` | Running but not Ready; `describe pod` shows HTTP 404 | Deliberately nonexistent readiness path; restore `/ready` | Validate endpoint contracts and inspect ready backends |
| `secret-key` | `CreateContainerConfigError`; inspect Pod events, not nonexistent application logs | Missing key reference in an existing Secret; restore `DATABASE_URL` key reference | Check names, namespaces and keys without exposing values |
| `crash` | `CrashLoopBackOff`; previous logs contain `DAY98_INTENTIONAL_CRASH`, exit 42 | Deliberately failing command; restore Uvicorn entrypoint | Check container exit reasons and `logs --previous` |
| `selector` | Ready Pod but no selected Service endpoints | Unmatched Service selector; restore selector matching the canary labels | Compare selectors with Pod labels and EndpointSlices |

Only a generated `day-98-fault-<scenario>.json` with PASS, the matching observation, and successful recovery verifies that scenario. A filename or a syntax-only inventory entry does not prove the test passed. The generated `day-98-troubleshooting.md` adds the per-run timestamps after final verification.

## What not to infer from these exercises

- Process health does not prove database connectivity; database connectivity does not prove every application operation.
- Sampled successful HTTP requests are not a guarantee of zero downtime.
- API Pod replacement is not PostgreSQL failover or a backup/restore test.
- A PDB object existing is not proof that the deferred drain exercise succeeded.
- Offline helper tests are not live-cluster validation.
- A server dry run is not an image-pull, scheduling, or business-transaction test.
- Git ignore rules do not remove already tracked secrets, and the index audit does not certify all history or screenshots.

## Before export or teardown

Preserve the genuine successful results, failed transcripts, reviewed diffs, and screenshots; commit the corrected helpers with the documentation. Verify the current Git index contains no real Secret or private kubeconfig.

Return next to the private database-export decision in [teardown-week14.md](teardown-week14.md). Do not delete the cluster or local credentials as part of publishing these notes. The deferred drain remains deferred; it does not block an independently verified Day 98 workflow.
