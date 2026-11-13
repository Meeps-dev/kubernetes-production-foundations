# Day 97 — production boundaries and operating decisions

## Intended behavior, not a completed-results claim
- Manual scaling first: 2 -> 4 -> 2; only then transfer scaling control to HPA.
- CPU HPA: 2–5 replicas, 60% of the API's 100m CPU request, not its 500m limit.
- Scale-down: 180-second stabilization plus at most one Pod removed per 60 seconds.
- Soft node spread prefers both workers without making maintenance on two workers unschedulable.
- PDB minAvailable=1 is an intentional lab budget; it does not promise production capacity at one replica.

## What a PDB protects
Evictions through the Eviction API, such as normal kubectl drain, are checked against
the budget. The lab temporarily requires both replicas and expects an eviction denial,
then restores minAvailable=1 for the actual drain.

## What it does not protect
A PDB does not stop direct Pod deletion, Deployment deletion, node loss, OOM failures,
HPA scale-down or application rollout changes from bypassing its eviction checks.
It does not back up PostgreSQL, reserve replacement capacity, or supply extra nodes.
HPA changes replicas, not node count; Pending replicas are not extra serving capacity.

## Local storage and shared machine
PostgreSQL uses a single node-local PVC. Never drain its node for this API lab.
All three kind nodes share the same Docker Desktop VM and physical 8 GiB Mac;
summing their reported capacity does not create separate physical capacity.
Keep the current conservative Docker allocation, stop competing labs, and watch pressure.

## TLS exceptions in the Metrics Server example
The official manifest's APIService commonly sets insecureSkipTLSVerify=true; inspect it.
The optional --kubelet-insecure-tls flag additionally disables kubelet serving-certificate
verification and is explicitly test-only. Keep this patch separate and do not promote it
to EKS/production. Production requires trusted kubelet certificates and a validated
Metrics Server serving certificate/CA bundle for the aggregation connection.

## Required production work beyond this lab
Measure representative workload behavior, tune requests/limits and HPA signals, provide
independent failure domains, establish database HA/backups and restore testing, reserve
maintenance capacity, and choose an appropriate metrics/control-plane HA setup.
Metrics Server is for autoscaling/resource summaries, not long-term observability.
