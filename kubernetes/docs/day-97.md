# Day 97 — Scaling, HPA, Availability, and Disruption

## What I Did
- Verified four healthy `meeps-api` replicas across both workers in `meeps-dev`.
- Confirmed all three nodes were `Ready`, PostgreSQL was running, and its PVC remained `Bound`.
- Reviewed the HPA configuration: 2–5 replicas, 60% CPU target, and 180-second scale-down stabilization.
- Investigated the failed HPA handoff using live Deployment counts, Pod conditions, and events.

## What I Learnt
- Manual scaling sets replica counts directly; HPA adjusts them using metrics. Metrics Server supplies CPU/memory measurements.
- CPU-utilization targets use CPU requests, not limits. Scale-down stabilization reduces rapid replica changes.
- A fixed `spec.replicas` in reapplied manifests can conflict with HPA; replica ownership must be transferred carefully.
- PDBs constrain voluntary evictions, not direct Pod deletion or node failures. Topology spread influences scheduling; uncordoning does not automatically rebalance existing Pods.
- The planned maintenance test must avoid PostgreSQL's worker because its storage is node-local.

## What Broke and the Fix
- **Error:** `Need two healthy replicas before ownership handoff`.
- **Cause:** Desired, updated, ready, and available counts were all `4`; the lab helper required exactly `2`. This was a helper prerequisite, not unhealthy Pods or a general HPA restriction.
- **Correction:** Run `python3 kubernetes/scripts/day97-lab.py manual 2`, verify two ready/available Pods, then rerun `python3 kubernetes/scripts/day97-lab.py handoff`.
- **Related errors:** HPA and load Job were not found because the handoff stopped before creating the HPA, and load generation could not proceed.

## Verification Status
Four healthy replicas and the handoff diagnosis are confirmed. Successful return to two, HPA creation, automatic scale-out/in, and PDB/drain recovery have not yet been verified in the shared output.
