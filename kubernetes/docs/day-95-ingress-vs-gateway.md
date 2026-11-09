# Day 95 — Ingress versus Gateway API

## Ingress
- `Ingress` declares HTTP hostname/path routing to Services; `IngressClass` identifies the controller implementation.
- A running controller implements these rules. This lab uses Traefik's Kubernetes Ingress provider.
- The Kubernetes Ingress API is frozen, not removed. It remains required in this roadmap.

## Gateway API
- `GatewayClass` identifies an implementation; `Gateway` declares listeners; `HTTPRoute` describes HTTP routing.
- Separating these resources supports distinct infrastructure/operator/application responsibilities and richer standardized routing.
- `kubernetes/examples/day-95-httproute.example.yaml` shows an equivalent hostname/path/backend. It is reference only, not deployed.
- Deployment requires compatible Gateway API CRDs, an enabled provider, Gateway-specific RBAC, a GatewayClass, and a programmed Gateway/listener. This lab does not silently install those prerequisites.

## Lab decisions and limits
- `/health`: process-only startup/liveness. `/ready`: authenticated `SELECT 1` using existing API runtime credentials.
- Probe DB connections use a separate, non-pooled engine with connect and statement timeout settings. These are not a universal wall-clock bound for every DNS/network failure.
- `SELECT 1` does not validate every table, migration, or transaction. Preserve the user/post tests.
- `maxUnavailable: 0` plus `maxSurge: 1` retains two old ready replicas while one new replica fails the deliberate readiness test.
- Traefik normally routes to ready Pod IPs from EndpointSlices rather than through the API Service ClusterIP. The Service still defines backend selection and ports.
- A blank Ingress ADDRESS can be normal for this local NodePort configuration. Prove reachability with host-side HTTP requests.
- HTTP is loopback-only on port 8080. Port 8443 is reserved; no certificate or HTTPS route is configured. No dashboard is exposed.
- One Traefik replica is a resource-conscious local setting, not production HA.
- Controller RBAC reads Services/Secrets/Ingresses/EndpointSlices in `meeps-dev`, updates Ingress status there, and reads cluster Nodes/IngressClasses. It is not cluster-admin, but can read Secrets in the application namespace; treat this controller as trusted infrastructure.
- API ServiceAccount token mounting stays disabled. Traefik needs its token to watch the Kubernetes API.
- No database password changes, migrations, PVC deletion, or cluster recreation are required.
- `k8s-v2` is a versioned tag, not inherently immutable. Do not repoint it; use a new tag for changed code.

## References
- https://kubernetes.io/docs/concepts/services-networking/ingress/
- https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/
- https://gateway-api.sigs.k8s.io/docs/concepts/api-overview/
- https://github.com/traefik/traefik/releases/tag/v3.7.17
- https://doc.traefik.io/traefik/v3.7/reference/install-configuration/providers/kubernetes/kubernetes-ingress/
- https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/ingress/
- https://doc.traefik.io/traefik/v3.7/reference/install-configuration/observability/logs-and-accesslogs/
- https://docs.sqlalchemy.org/en/20/core/pooling.html
- https://www.postgresql.org/docs/15/libpq-connect.html
