#!/usr/bin/env bash
# Fresh, read-only final checks. Never creates users, posts, or placeholder PASS files.
set -euo pipefail
set +x
OUT='kubernetes/docs'
REPORT="$OUT/day-95-final-verification.txt"
SELECTOR='app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev'
k() { kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" --context kind-meeps-k8s-cluster -n meeps-dev "$@"; }
t() { kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" --context kind-meeps-k8s-cluster -n traefik-system "$@"; }
fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
for FILE in "$OUT/day-94-fixture.json" "$OUT/day-95-readiness-drill.json" kubernetes/scripts/day95-test-ingress.py; do
  [ -s "$FILE" ] || fail "Missing prerequisite result/file: $FILE"
done
[ "$(k config current-context)" = kind-meeps-k8s-cluster ] || fail 'Wrong context.'
{
  printf '===== DAY 95 FINAL VERIFICATION =====\n'
  date -u '+Captured: %Y-%m-%dT%H:%M:%SZ'
  k config current-context
  k rollout status deployment/meeps-api --timeout=180s
  t rollout status deployment/traefik --timeout=180s
  [ "$(k get deployment meeps-api -o jsonpath='{.spec.replicas} {.status.updatedReplicas} {.status.readyReplicas} {.status.availableReplicas}')" = '2 2 2 2' ] || fail 'Expected 2/2/2/2 API replicas.'
  [ "$(k get deployment meeps-api -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')" = meeps-users-posts-api:k8s-v2 ] || fail 'Wrong API image.'
  for PROBE in startupProbe livenessProbe readinessProbe; do
    PATH_VALUE="$(k get deployment meeps-api -o jsonpath="{.spec.template.spec.containers[?(@.name==\"api\")].${PROBE}.httpGet.path}")"
    EXPECTED=/health
    [ "$PROBE" != readinessProbe ] || EXPECTED=/ready
    [ "$PATH_VALUE" = "$EXPECTED" ] || fail "Wrong $PROBE path: $PATH_VALUE"
    printf '%s: %s\n' "$PROBE" "$PATH_VALUE"
  done
  k wait --for=condition=Ready pods -l "$SELECTOR" --timeout=180s
  k get deployment,replicaset,pods -l "$SELECTOR" -o wide
  printf '\n===== READY BACKENDS =====\n'
  PODS="$(k get pods -l "$SELECTOR" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | LC_ALL=C sort)"
  BACKENDS="$(k get endpointslice -l kubernetes.io/service-name=meeps-api -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.targetRef.name}{"\n"}{end}' | LC_ALL=C sort -u)"
  [ "$(printf '%s\n' "$PODS" | wc -l | tr -d ' ')" = 2 ] || fail 'Expected exactly two remaining API Pods.'
  [ "$PODS" = "$BACKENDS" ] || fail 'Ready Service endpoints differ from the current API Pods.'
  k get endpointslice -l kubernetes.io/service-name=meeps-api -o wide
  printf '\n===== INGRESS CONTROLLER AND ROUTE =====\n'
  k get ingressclass meeps-traefik
  k get ingress meeps-api -o wide
  t get deployment,pods,service -o wide
  [ "$(k get ingress meeps-api -o jsonpath='{.spec.ingressClassName}')" = meeps-traefik ] || fail 'Wrong IngressClass.'
  IMAGE="$(t get deployment traefik -o jsonpath='{.spec.template.spec.containers[0].image}')"
  case "$IMAGE" in *@sha256:*) printf 'Controller image: %s\n' "$IMAGE";; *) fail 'Controller image is not digest-pinned.';; esac
  printf '\n===== EXTERNAL HTTP THROUGH INGRESS =====\n'
  for ROUTE in / /health /ready /users/; do
    printf '\nGET %s\n' "$ROUTE"
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
      --resolve api.meeps.local:8080:127.0.0.1 "http://api.meeps.local:8080$ROUTE"
    printf '\n'
  done
  printf '\n===== ORIGINAL DAY 94 RECORDS THROUGH TRAEFIK — GET ONLY =====\n'
  k exec -i deployment/meeps-api -c api -- python - \
    --fixture-json "$(cat "$OUT/day-94-fixture.json")" \
    < kubernetes/scripts/day95-test-ingress.py
  printf '\n===== SAVED READINESS / TRAFFIC EXCLUSION PROOF =====\n'
  k exec -i deployment/meeps-api -c api -- python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"]=="PASS" and r["requests_checked"]==20; print(json.dumps(r,indent=2))' \
    < "$OUT/day-95-readiness-drill.json"
  printf '\n===== DATABASE STORAGE =====\n'
  k rollout status statefulset/postgres --timeout=180s
  k wait --for=jsonpath='{.status.phase}'=Bound pvc/postgres-data-postgres-0 --timeout=120s
  k get pvc postgres-data-postgres-0
  printf '\n===== CURRENT GIT INDEX =====\n'
  [ -z "$(git ls-files -- .local/)" ] || fail 'Private local files are tracked/staged; do not commit.'
  git check-ignore -v .local/meeps-dev/api-secret.local.yaml
  printf '\nDAY 95 CORE CHECKS PASSED. TLS and live Gateway API deployment are not included.\n'
} 2>&1 | tee "$REPORT.tmp"
mv "$REPORT.tmp" "$REPORT"
printf '\nSaved: %s\n' "$REPORT"
