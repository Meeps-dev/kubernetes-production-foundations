# Day 97 file guide — scaling, HPA and disruption

This package implements the agreed Day 97 lab. It does not contain execution results.
Run from `kubernetes-production-foundations` after sourcing the local-cluster session helper.
Host requirement: Python 3.9+ and the existing kubectl/kind/Docker tools. No host pip install.

## Files and scope
- `base/hpa.yaml`: autoscaling/v2, 2–5 replicas, CPU utilization 60% of requests, controlled rates.
- `base/pdb.yaml`: policy/v1, minAvailable 1, explicit selector, AlwaysAllow unhealthy eviction policy.
- `examples/day-97-topology.patch.yaml`: API worker selection and soft per-host spreading, per revision.
- `examples/day-97-load-job.yaml`: bounded GET-only load using the existing week14-v2 image.
- `scripts/day97-load.py`: request rate/concurrency/duration limits; no database writes or secrets.
- `scripts/day97-lab.py`: individual checkpoints, always with explicit kubeconfig/context.
- `scripts/test_day97.py`: offline tests; these do not certify cluster behavior.
- `cluster/metrics-server/kind-local-tls.patch.json`: optional local-test-only kubelet TLS workaround.

The official Metrics Server components manifest must be downloaded separately, at version v0.9.1.
No bundled file is presented as a copy of the upstream release manifest.

## Checkpoint order
```bash
python3 kubernetes/scripts/test_day97.py
python3 kubernetes/scripts/day97-lab.py preflight
python3 kubernetes/scripts/day97-lab.py manual 4
python3 kubernetes/scripts/day97-lab.py manual 2
# Install Metrics Server and confirm kubectl top separately.
python3 kubernetes/scripts/day97-lab.py handoff
# Wait until HPA reports AbleToScale=True and ScalingActive=True.
python3 kubernetes/scripts/day97-lab.py load-start --rps 200
python3 kubernetes/scripts/day97-lab.py observe out --timeout 480
python3 kubernetes/scripts/day97-lab.py load-stop
python3 kubernetes/scripts/day97-lab.py observe in --timeout 900
python3 kubernetes/scripts/day97-lab.py spread
kubectl apply --dry-run=server -f kubernetes/base/pdb.yaml
kubectl apply -f kubernetes/base/pdb.yaml
python3 kubernetes/scripts/day97-lab.py drain
python3 kubernetes/scripts/day97-lab.py final
```

Manual scaling refuses to run after the HPA is created. The handoff removes only
replicas from the client-side last-applied annotation, then removes replicas from
the local Deployment file, applies that file, and creates the HPA. It preserves
live replicas during handoff. Do not blindly apply old Day 94–96 replica-bearing
manifests, or rerun old fixed-replica repair steps, while the HPA owns scaling.

## Load and observations
The rate is an upper target, not guaranteed throughput. Connections close to give
new Service backends new connections. Queue size, concurrent requests, timeouts,
CPU/memory limits, and overall Job deadline bound the test. Skipped offered
requests mean the client could not keep up; read the log, not only the target rate.
There is no guarantee this workload will cause scaling on every machine. A pass
requires at least 3 observed ready API Pods and a healthy HPA. Five replicas are a
cap, not a required outcome. Stop at the first pressure/unhealthy behavior.

`observe in` requires load-stop and observes two ready replicas stably for 30 seconds.
Stabilization is not a promise of scale-in at an exact time.

## Drain guardrails and permitted changes
The helper does the following only when `drain` is explicitly run:
1. Requires healthy two-replica state, HPA at two, no load Job, and API Pods on both workers.
2. Chooses a worker other than the one running PostgreSQL; records it under docs/.
3. Refuses unknown or stateful non-DaemonSet occupants on that worker.
4. Cordons it. If Traefik or Metrics Server occupies it, rolls that known Deployment
   using `rollout restart` and waits for its replacement elsewhere before proceeding.
   This maintenance restart changes the restartedAt annotation/revision; it does
   not replace their source manifests or change their images/security settings.
5. Temporarily changes the API PDB to minAvailable=2. An actual drain must be refused
   by the PDB and time out; this refusal is expected test evidence.
6. Restores minAvailable=1 and drains normally through the eviction API.
7. Checks ready replacement Pods, the unchanged PostgreSQL Pod UID and original records.
8. Restores the tracked PDB and uncordons in a finally block on normal failures/interrupts.
   Force-killing the process or losing the API can prevent cleanup; use recover.

`--delete-emptydir-data` permits loss of the API's disposable /tmp, not PVC deletion.
DaemonSets are ignored, not deleted. The helper never disables eviction, passes
--force, drains the control plane/database node, or deletes a PVC.
HTTP /ready samples are taken through host-side Ingress during the maintenance.
They are samples, not proof of an SLA or absence of every possible interruption.

## Recovery and result files
```bash
python3 kubernetes/scripts/day97-lab.py recover
```
This stops the named load Job, restores the normal PDB and uncordons the recorded
worker. It does not turn incomplete exercises into passing results.

All records are flat `kubernetes/docs/day-97-*` files. A failed checkpoint keeps a
`.tmp` transcript. Review timestamps and the latest failure; do not rename it into
a successful report or cite stale results. Final checks verify earlier result files
and fresh cluster state, but do not rerun the load/drain exercise.

After uncordon, current Pods may remain on the other worker. Soft topology spreading
acts at scheduling time; it does not automatically move running Pods back.
