# Architecture — Kubernetes Production Foundations

## Execution boundary

The lab uses Docker Desktop on an Intel Mac with 8 GiB physical RAM. kind runs one control-plane and two worker node containers. All share one physical host: three containers are not three independent failure domains. The Kubernetes API is accessed through the dedicated `~/.kube/meeps-k8s-cluster.yaml` file.

## Request flow

1. A client connects to `127.0.0.1:8080` and supplies `Host: api.meeps.local`.
2. kind maps that port to `30080` on the control-plane node container.
3. Traefik's NodePort Service sends traffic to the controller.
4. Ingress `meeps-api`, class `meeps-traefik`, selects the API Service on port 80.
5. Traefik uses discovered ready backend addresses to reach API containers on 8000.
6. API transactions connect through `postgres:5432` to the database Pod.

`127.0.0.1:8443 -> 30443` is reserved. The completed core workflow is HTTP; the mapping does not itself provide certificates or TLS routing.

## Workload and configuration model

- Namespace: `meeps-dev` for API, database, migrations and controlled exercises.
- API Deployment: stateless processes, resource budgets, non-root security context and temporary `/tmp` volume.
- Configuration: ConfigMaps for ordinary settings; Secrets for credentials. Secret references—not values—may be versioned.
- Database identities: bootstrap administrator, `meeps_migrator` database/schema owner, and `meeps_api` with reviewed runtime grants.
- Database: one PostgreSQL StatefulSet replica; `postgres-headless` for stable identity and `postgres` for client discovery. PVC `postgres-data-postgres-0` binds to node-local storage.
- Migrations: Alembic Job, separate from API replicas, with explicit completion/head/table checks. Job completion is not a guarantee of exactly-once execution.

## Control loops

- Startup and liveness use `/health`. Readiness uses database-aware `/ready`.
- Metrics Server supplies resource measurements. HPA adjusts API replicas within 2–5.
- PDB `minAvailable: 1` constrains normal voluntary evictions. It does not protect direct deletion or every failure.
- A soft worker-host topology rule influences new placement. Uncordon does not rebalance existing Pods.

## Day 98 canary boundary

`meeps-day98-canary` is one temporary replica and a separate ClusterIP Service. Its application labels are different from the real API's selectors. The main Ingress, HPA and PDB do not select it. It reuses the existing image and runtime Secret references and runs GET/readiness checks only. It does not create users/posts, execute migrations, mount the PostgreSQL PVC or change database passwords.

## Limits and production direction

The database is neither replicated nor backed up by retaining its PVC. Deleting kind's node containers removes its local storage. Tests are small controlled exercises, not capacity measurements, load-test certification or an availability SLA.

For the future EKS lab, separately design managed database resilience, durable storage, network policy enforcement, TLS, external secret delivery, API authentication/authorization, metrics/log retention, and verified backup/restore. None is implied by the local deployment.
