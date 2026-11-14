# Kubernetes Production Foundations

**FastAPI · PostgreSQL · kind · Traefik · Horizontal Pod Autoscaling**

A production-style local Kubernetes lab that takes the existing **Meeps Users and Posts API** from its ECS container workflow into declarative Kubernetes deployment and day-to-day operations.

The focus is not just starting containers. It is understanding workload reconciliation, configuration boundaries, persistent data, health checks, routing, release management, autoscaling, and diagnosis using actual Pod conditions, events, logs, and saved test results.

> **Scope:** Week 14, Days 92–98 of the Meeps Cloud/Platform Engineering roadmap. This is a local learning environment not a production-hosted service, a highly available database, or a zero-downtime guarantee.

## Project status and evidence boundaries

The implementation includes the API/database manifests, probe and Ingress configuration, rollout exercises, HPA/PDB configuration, and isolated failure-testing tools. Shared runtime captures show a working three-node cluster, available API replicas, PostgreSQL with a bound PVC, and CPU metrics feeding the HPA.

**The Day 97 worker-drain exercise is deferred, not passed.** Attempts were blocked during controller relocation. Day 98 was deliberately changed to use fresh live safety checks instead of requiring a successful drain completion file. Its baseline records this as `DEFERRED_NOT_VERIFIED`.

This is the **pre-export, pre-teardown documentation snapshot**. Final validation, each failure recovery, and cleanup are established by their generated result files—not by this README. A missing result, a failed result, or an incomplete `.tmp` transcript must not be presented as a pass.

## Architecture

```text
Client on the Mac
  HTTP Host: api.meeps.local
  127.0.0.1:8080
        |
        v
kind control-plane port mapping -> NodePort 30080
        |
        v
Traefik controller [traefik-system]
  IngressClass: meeps-traefik
        |
        v
Ingress: meeps-api [meeps-dev]
  host: api.meeps.local | path: / | Prefix
        |
        v
meeps-api Service :80 -> selected ready API Pod endpoints :8000
        |
        v
postgres ClusterIP Service :5432
        |
        v
PostgreSQL StatefulSet -> postgres-data-postgres-0 PVC

ConfigMaps / local Secrets -> application and database configuration
Alembic Job              -> schema migrations before application use
Metrics Server           -> CPU metrics -> HPA -> API replica count
PDB / topology spread    -> eviction budget and placement preference
Isolated Day 98 canary   -> fault tests, separate from API traffic
```

Traefik is configured to discover backend Pod addresses through Kubernetes. The API Service defines selection; its ClusterIP is not necessarily an intermediate network hop in the proxied request.

The cluster has **one control-plane container and two worker containers on one Mac**. They are not independent machines or availability zones. Host mapping `127.0.0.1:8443 -> 30443` is reserved; the core exercise provides **HTTP**, not a completed TLS deployment.

More detail: [architecture](kubernetes/docs/architecture-week14.md).

## Stack and lab configuration

| Component | Configuration used in the lab |
|---|---|
| Application | FastAPI, SQLAlchemy, psycopg2, Alembic; Python 3.12 container |
| Database | PostgreSQL 15 Bookworm image, resolved to a digest during setup |
| Local runtime | Docker Desktop; Intel Mac with 8 GiB physical memory |
| Cluster | `meeps-k8s-cluster`; kind `v0.33.0`; nodes reported Kubernetes `v1.37.0` |
| Access | Context `kind-meeps-k8s-cluster`; dedicated kubeconfig outside the repository |
| Namespaces | `meeps-dev`, `traefik-system`, and system components in `kube-system` |
| Ingress | Traefik `v3.7.17` release selected in setup; explicit `meeps-traefik` class |
| Metrics | Metrics Server `v0.9.1`; resource metrics rather than historical monitoring |
| Current application release | `meeps-users-posts-api:week14-v2` |
| Autoscaling | `autoscaling/v2`; 2–5 replicas; 60% CPU-request utilization target |

These are the recorded/configured lab versions, not recommendations to install the latest release. Per-day captures and saved manifests identify the actual images used.

## Repository layout

```text
application/
  app/                      API routes, database settings, readiness, release identity
  alembic/                  Versioned database migrations
  tests/                    Application and probe tests
  Dockerfile                Multi-stage, non-root application image
  compose.yaml              Retained local application preflight configuration

kubernetes/
  base/                     Current application and database manifests
  cluster/                  kind, Traefik, and Metrics Server configuration
  examples/                 Placeholder Secrets, patches, optional APIs, failure examples
  scripts/                  Setup, test, validation, and cleanup helpers
  docs/                     Flat day-NN-* outputs and operational Markdown files

.local/                     Ignored local credentials, repair backups, validation tools
README.md                   This project overview
```

**Do not recursively apply `kubernetes/`.** The tree contains current resources, one-off Jobs, historical captures, patches, optional references, and deliberately invalid examples. Apply only reviewed resources appropriate to the current checkpoint.

## Implementation journey

| Day | Work and learning |
|---|---|
| 92 | Kubernetes architecture; local cluster; namespaces, labels, kubeconfig and contexts; command documentation |
| 93 | ConfigMaps and Secrets; PostgreSQL Services/StatefulSet/PVC; separate Alembic migration Job |
| 94 | API Deployment, ReplicaSet and ClusterIP Service; runtime database role; create/read fixture and Pod-replacement test |
| 95 | Database-aware readiness; startup/liveness separation; Traefik Ingress; unready-backend traffic exercise |
| 96 | Visible release identity; rolling update; invalid-image rollout; explicit rollback with sampled HTTP requests |
| 97 | Manual scaling; resource metrics; HPA ownership; topology preference and PDB; drain attempted but deferred |
| 98 | Four isolated canary faults; manifest/diff review; security and Git checks; documentation and guarded cleanup |

The existing application was copied from the ECS repository. Its AWS infrastructure and deployment workflows were not imported as the Kubernetes environment.

## Database and credential boundaries

PostgreSQL uses one StatefulSet replica and the `standard` local storage class. `postgres-headless` supplies StatefulSet network identity; `postgres` supplies the client connection name. The database claim is `postgres-data-postgres-0`.

Three database roles have different responsibilities:

| Role | Responsibility |
|---|---|
| `postgres` | Bootstrap administration |
| `meeps_migrator` | Own the application database/schema and apply Alembic revisions; not a superuser |
| `meeps_api` | Connect, use the schema, select/insert users and posts, and use their ID sequences |

The API does not receive administrator or migration-owner credentials. New API operations require reviewed grants rather than blanket permission expansion.

Real Secret manifests are generated locally under `.local/meeps-dev/`; only placeholder examples belong in Git. Never publish passwords, credential-bearing URLs, decoded Secret objects, or kubeconfig contents.

Initialization SQL runs when PostgreSQL initializes an empty data directory. Editing an initialization ConfigMap does not rerun that SQL against an existing database. Likewise, changing a Kubernetes Secret alone is not a PostgreSQL password-rotation procedure.

A retained PVC is **not a backup**. Deleting the kind node containers destroys the database's node-local storage unless the data has been preserved separately.

## Application health and security

| Endpoint/control | Purpose |
|---|---|
| `/health` | Process responsiveness; used for startup and liveness |
| `/ready` | Authenticated `SELECT 1`; HTTP 200 when ready and 503 on database errors |
| `/version` | Build identifier `week14-v2` and serving Pod name |
| UID/GID `10001` | Non-root API process |
| Dropped capabilities, no privilege escalation, `RuntimeDefault` seccomp | Restrict container privileges |
| Read-only root filesystem and bounded writable `/tmp` | Limit writable container paths |
| No mounted application ServiceAccount token | Avoid unnecessary Kubernetes API credentials |
| Requests `100m` CPU / `128Mi` memory; limits `500m` / `256Mi` | Initial local resource budgets, not production sizing |
| 30-second Pod termination grace; 20-second Uvicorn shutdown budget | Bounded graceful shutdown |

Readiness uses a separate non-pooled database engine so probe timeouts do not alter normal transaction settings. It does not prove every migration or business operation is correct. Liveness stays independent of temporary database availability.

Controller ServiceAccounts do require API access and have their own RBAC. Namespace Pod Security labels use **audit/warn**, not enforcement. NetworkPolicy enforcement, API authentication, production TLS, and external secret management are not claimed by this lab.

## Releases, autoscaling, and disruptions

The release exercise uses `RollingUpdate`, `maxUnavailable: 0`, `maxSurge: 1`, `minReadySeconds: 10`, `progressDeadlineSeconds: 180`, and `revisionHistoryLimit: 5`.

Local API images are loaded into kind with `imagePullPolicy: Never`. Their version tags are a lab convention, not registry-enforced immutability. The intentionally invalid-image exercise uses a separate example with `Always` so the failure actually exercises image pulling. Rollback restores the recorded healthy Pod template; it does not reverse database migrations.

HPA owns the current API replica count. The tracked Deployment must **omit `spec.replicas`**. Its 60% CPU target is measured against requests, not limits. Scale-up permits one additional Pod per 30-second policy window; scale-down uses a 180-second stabilization window and at most one removal per 60-second policy window.

The topology rule prefers spreading replicas across workers with `ScheduleAnyway`. The normal PDB is `minAvailable: 1`, with `unhealthyPodEvictionPolicy: AlwaysAllow`. Neither configuration establishes production high availability.

The drain investigation exposed a hard Metrics Server hostname selector, followed by a separate Traefik relocation timeout. The maintenance exercise remains deferred; the troubleshooting guide preserves what was observed without inventing a successful drain result.

## Access and routine checks

Run from the repository root in each new terminal:

```bash
cd "$HOME/kubernetes-production-foundations"
source kubernetes/scripts/use-local-cluster.sh
kubectl config current-context
```

The session selects `~/.kube/meeps-k8s-cluster.yaml`, Docker Desktop, and `kind-meeps-k8s-cluster`.

Test the host-mapped Ingress route without changing `/etc/hosts`:

```bash
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
  --resolve api.meeps.local:8080:127.0.0.1 \
  http://api.meeps.local:8080/ready

curl --noproxy '*' --fail --silent --show-error --max-time 10 \
  --resolve api.meeps.local:8080:127.0.0.1 \
  http://api.meeps.local:8080/version
```

Existing business routes are `POST/GET /users/` and `POST/GET /posts/users/{user_id}`. The saved Day 94 fixture contains synthetic user/post records. Persistence checks read those same records; creating replacements is not proof of persistence.

Useful inspection commands:

```bash
kubectl get nodes -o wide
kubectl -n meeps-dev get deployment,replicaset,pods,svc,ingress,hpa,pdb,pvc
kubectl -n meeps-dev get endpointslice -l kubernetes.io/service-name=meeps-api
kubectl -n meeps-dev logs -l app.kubernetes.io/name=meeps-api -c api --prefix --tail=30
kubectl top nodes
kubectl -n meeps-dev top pods -l app.kubernetes.io/name=meeps-api --containers
```

For a fresh installation, follow the staged Day 92–98 setup and file guides. New credentials, image builds/imports, database initialization, runtime grants, and ordered controller installation are required. This is not a one-command deployment or an instruction to replay old failure checkpoints on a running HPA-controlled workload.

## Failure engineering and validation

Day 98 uses a temporary `meeps-day98-canary` Deployment and Service with separate application labels. The main Service, Ingress, HPA, and PDB do not select it. It reuses runtime configuration but runs no migrations, mounts no database PVC, and does not create business records.

| Controlled fault | Expected diagnosis | Recovery |
|---|---|---|
| Wrong readiness path | Running but unready; readiness HTTP 404 | Restore `/ready` |
| Missing Secret key reference | `CreateContainerConfigError` | Restore the key reference, not the password |
| Deliberately failing command | `CrashLoopBackOff`, exit 42, known log marker | Restore Uvicorn command/arguments |
| Unmatched Service selector | Ready Pod, no selected backend | Restore matching selector |

Each drill is verified only by its own generated PASS result and the final live checks. Detailed real incidents and fixes are in [Week 14 troubleshooting](kubernetes/docs/troubleshooting-week14.md).

The Day 98 validator distinguishes current manifests, renderable patches, placeholder Secrets, kind configuration, optional Gateway API references, and saved captures. Server-side dry runs do not modify the cluster. `kubectl diff` exit 1 means differences were found, not that the command failed.

Use the corrected Day 98 helper: its preflight is independent of the deferred drain, and patch rendering uses the target resource's namespace. Review actual differences instead of blanket-applying the tree or disabling validation.

## Proof and documentation

All generated files remain directly under `kubernetes/docs/`. Typical completion records include `day-94-api-verification.txt`, `day-95-final-verification.txt`, `day-96-final-verification.txt`, `day-97-scale-out.json`, `day-97-scale-in.json`, and `day-98-final-result.json`.

Do not substitute the missing `day-97-final-result.json` or `day-97-drain-result.json` with fabricated files. Successful Day 98 checks do not retroactively complete Day 97 maintenance.

Retain screenshots of Pods, Services, Pod logs, rolling updates, and fault diagnosis. Only describe a traffic exercise as having **no failed requests observed in the recorded samples** when the output supports it. This is not a measured availability SLA.

Operational documents:

- [Architecture](kubernetes/docs/architecture-week14.md)
- [Week-wide troubleshooting](kubernetes/docs/troubleshooting-week14.md)
- [kubectl command reference](kubernetes/docs/kubectl-commands-week14.md)
- [Security, cost, and production gaps](kubernetes/docs/security-cost-week14.md)
- [Day 98 validation contract](kubernetes/docs/day-98-file-guide.md)
- [Manifest-diff review](kubernetes/docs/day-98-diff-review.md)
- [Optional export and teardown](kubernetes/docs/teardown-week14.md)

## Cleanup, cost, and remaining boundaries

Before deletion, save verified results and screenshots, review the Git index for credentials, commit/push the documentation, and decide whether to retain a private database export. **Export is separate from teardown; deciding to export does not authorize cluster deletion.**

The guarded teardown targets only `meeps-k8s-cluster`, verifies its node containers are absent, and removes the known local Secret files and dedicated lab kubeconfig. Optional image cleanup targets the four named Week 14 API tags without forced deletion or a global prune. Cleanup is not complete until the teardown result exists and has passed.

Week 14 uses local CPU, memory, disk, power, and network resources. These commands do not deploy AWS infrastructure or audit charges from earlier AWS labs.

Production work still requires resilient database/storage design, tested backup and restore, trusted TLS, external secret handling, network isolation, image provenance/scanning, durable monitoring, measured capacity, and a successfully rehearsed maintenance strategy. EKS, Helm/Kustomize packaging, and GitOps belong to later roadmap stages.

**Roadmap coverage:** tasks 78–86 cover local cluster setup, Deployment, Service, ConfigMap/Secret, probes, rolling updates, scaling, Pod failure diagnosis, and `kubectl` documentation. StatefulSets, PVCs, role separation, migration Jobs, PDBs, and guarded cleanup are this project's additional implementation scope.
