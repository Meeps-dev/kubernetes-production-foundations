#!/usr/bin/env bash
# Controlled local-lab fault. Requires finished Day 95 ingress + probes.
# Intentionally changes ONLY the live readiness path, then restores tracked YAML.
set -euo pipefail
set +x

OUT='kubernetes/docs'
SELECTOR='app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev'
MANIFEST='kubernetes/base/api-deployment.yaml'
RESTORE_NEEDED=0
BAD_POD=''

k() {
  kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
    --context kind-meeps-k8s-cluster -n meeps-dev "$@"
}
t() {
  kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
    --context kind-meeps-k8s-cluster -n traefik-system "$@"
}
fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
restore() {
  printf '\n===== RESTORE THE TRACKED, CORRECT DEPLOYMENT =====\n'
  k apply -f "$MANIFEST" || return 1
  k rollout status deployment/meeps-api --timeout=180s || return 1
  if [ -n "$BAD_POD" ] && [ -n "$(k get pod "$BAD_POD" --ignore-not-found -o name)" ]; then
    k wait --for=delete "pod/$BAD_POD" --timeout=90s || return 1
  fi
  RESTORE_NEEDED=0
}
cleanup() {
  STATUS=$?
  trap - EXIT
  if [ "$RESTORE_NEEDED" -eq 1 ]; then
    printf '\nDrill interrupted or failed. Attempting recovery from the saved manifest.\n' >&2
    if ! restore; then
      printf 'RECOVERY FAILED: manually apply kubernetes/base/api-deployment.yaml and inspect rollout.\n' >&2
      STATUS=1
    fi
  fi
  exit "$STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[ -s "$MANIFEST" ] || fail 'Run from the repository root.'
[ -s kubernetes/scripts/day95-check-access.py ] || fail 'Missing access-log verifier.'
[ "$(k config current-context)" = kind-meeps-k8s-cluster ] || fail 'Wrong context.'
[ "$(k get deployment meeps-api -o jsonpath='{.spec.replicas}')" = 2 ] || fail 'Expected two API replicas.'
[ "$(k get deployment meeps-api -o jsonpath='{.spec.strategy.rollingUpdate.maxUnavailable}')" = 0 ] || fail 'Expected maxUnavailable: 0.'
[ "$(k get deployment meeps-api -o jsonpath='{.spec.strategy.rollingUpdate.maxSurge}')" = 1 ] || fail 'Expected maxSurge: 1.'
[ "$(k get deployment meeps-api -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}')" = meeps-users-posts-api:k8s-v2 ] || fail 'Expected the Day 95 k8s-v2 image.'
[ "$(k get deployment meeps-api -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].readinessProbe.httpGet.path}')" = /ready ] || fail 'Readiness must start at /ready.'
[ "$(k create --dry-run=client -f "$MANIFEST" -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].readinessProbe.httpGet.path}')" = /ready ] || fail 'Tracked manifest must retain /ready for recovery.'
[ "$(k get service meeps-api -o jsonpath='{.spec.publishNotReadyAddresses}')" != true ] || fail 'Service must not publish unready backends.'
[ "$(k get service meeps-api -o go-template='{{with .metadata.annotations}}{{index . "traefik.ingress.kubernetes.io/service.nativelb"}}{{end}}')" != true ] || fail 'Log proof requires direct Pod routing, not nativeLB.'

k rollout status deployment/meeps-api --timeout=180s
t rollout status deployment/traefik --timeout=180s
[ "$(k get deployment meeps-api -o jsonpath='{.status.availableReplicas}')" = 2 ] || fail 'Both API replicas must be available.'
mkdir -p "$OUT"

curl --noproxy '*' --fail --silent --show-error --max-time 10 \
  --resolve api.meeps.local:8080:127.0.0.1 \
  http://api.meeps.local:8080/ready >/dev/null
k get pods -l "$SELECTOR" -o wide > "$OUT/day-95-pods-before-drill.txt"

RESTORE_NEEDED=1
printf '\n===== INTENTIONAL WRONG READINESS PATH =====\n'
k patch deployment meeps-api --type=strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"api","readinessProbe":{"httpGet":{"path":"/__day95_wrong_ready"}}}]}}}}'

# The rollout retains old ready Pods while its one new Pod fails readiness.
for ATTEMPT in {1..60}; do
  for POD in $(k get pods -l "$SELECTOR" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
    PROBE_PATH="$(k get pod "$POD" -o jsonpath='{.spec.containers[?(@.name=="api")].readinessProbe.httpGet.path}')"
    if [ "$PROBE_PATH" = /__day95_wrong_ready ]; then BAD_POD="$POD"; break; fi
  done
  [ -n "$BAD_POD" ] && break
  sleep 2
done
[ -n "$BAD_POD" ] || fail 'Faulty replacement did not appear; inspect scheduling/resources.'
printf 'Faulty Pod: %s\n' "$BAD_POD"
k wait --for=jsonpath='{.status.containerStatuses[?(@.name=="api")].started}'=true \
  "pod/$BAD_POD" --timeout=150s
k wait --for=condition=Ready=false "pod/$BAD_POD" --timeout=90s

EVENT_FOUND=0
for ATTEMPT in {1..30}; do
  k get events --field-selector "involvedObject.name=$BAD_POD" \
    -o jsonpath='{range .items[*]}{.message}{"\n"}{end}' \
    > "$OUT/day-95-readiness-events.txt"
  if grep -q 'Readiness probe failed:.*404' "$OUT/day-95-readiness-events.txt"; then
    EVENT_FOUND=1; break
  fi
  sleep 2
done
[ "$EVENT_FOUND" = 1 ] || fail 'No readiness HTTP 404 event observed.'
k describe pod "$BAD_POD" > "$OUT/day-95-unready-pod.txt"
k get pods -l "$SELECTOR" -o wide | tee "$OUT/day-95-pods-during-drill.txt"
cat "$OUT/day-95-readiness-events.txt"

BAD_IP="$(k get pod "$BAD_POD" -o jsonpath='{.status.podIP}')"
RESTARTS_BEFORE="$(k get pod "$BAD_POD" -o jsonpath='{.status.containerStatuses[?(@.name=="api")].restartCount}')"
[ -n "$BAD_IP" ] || fail 'Faulty Pod has no IP.'

# Explicitly wait for the EndpointSlice ready=false observation.
ENDPOINT_FALSE=0
for ATTEMPT in {1..30}; do
  VALUE="$(k get endpointslice -l kubernetes.io/service-name=meeps-api \
    -o jsonpath="{range .items[*].endpoints[?(@.targetRef.name==\"$BAD_POD\")]}{.conditions.ready}{end}")"
  if [ "$VALUE" = false ]; then ENDPOINT_FALSE=1; break; fi
  sleep 2
done
[ "$ENDPOINT_FALSE" = 1 ] || fail 'Faulty endpoint was not observed with ready=false.'
k get endpointslice -l kubernetes.io/service-name=meeps-api -o json \
  > "$OUT/day-95-endpoints-during-drill.json"
READY_IPS="$(k get endpointslice -l kubernetes.io/service-name=meeps-api \
  -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.addresses[0]}{"\n"}{end}' | LC_ALL=C sort -u)"
[ "$(printf '%s\n' "$READY_IPS" | wc -l | tr -d ' ')" = 2 ] || fail 'Expected two ready backends.'
GOOD_POD="$(k get endpointslice -l kubernetes.io/service-name=meeps-api \
  -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.targetRef.name}{"\n"}{end}' | head -n 1)"
[ -n "$GOOD_POD" ] || fail 'No ready Pod available to run log verification.'

MARKER="day95-$(date -u +%Y%m%dT%H%M%S)-$$"
printf '\n===== SEND 20 REQUESTS THROUGH HOST PORT AND INGRESS =====\n'
: > "$OUT/day-95-ingress-drill-requests.txt"
for REQUEST in {1..20}; do
  CODE="$(curl --noproxy '*' --silent --show-error --max-time 10 \
    --resolve api.meeps.local:8080:127.0.0.1 \
    -H "X-Meeps-Drill: $MARKER" \
    -o /dev/null -w '%{http_code}' \
    "http://api.meeps.local:8080/health?day95=$MARKER")"
  printf 'Request %02d: HTTP %s\n' "$REQUEST" "$CODE" | tee -a "$OUT/day-95-ingress-drill-requests.txt"
  [ "$CODE" = 200 ] || fail "Ingress returned $CODE."
  sleep 0.2
done
sleep 2
t logs deployment/traefik --since=5m > "$OUT/day-95-ingress-drill-access.jsonl"
k exec -i "$GOOD_POD" -c api -- python -c "$(cat kubernetes/scripts/day95-check-access.py)" \
  --marker "$MARKER" --bad-ip "$BAD_IP" --ready-ips "$READY_IPS" --expected 20 \
  < "$OUT/day-95-ingress-drill-access.jsonl" > "$OUT/day-95-readiness-drill.json.tmp"

RESTARTS_AFTER="$(k get pod "$BAD_POD" -o jsonpath='{.status.containerStatuses[?(@.name=="api")].restartCount}')"
[ "$RESTARTS_BEFORE" = "$RESTARTS_AFTER" ] || fail 'Unexpected container restart during the readiness-only drill.'
printf 'Faulty Pod restart count unchanged: %s\n' "$RESTARTS_AFTER" \
  | tee "$OUT/day-95-restarts-during-drill.txt"
restore
k get pods -l "$SELECTOR" -o wide | tee "$OUT/day-95-pods-after-drill.txt"
[ "$(k get deployment meeps-api -o jsonpath='{.status.availableReplicas}')" = 2 ] || fail 'Expected two available replicas after repair.'
mv "$OUT/day-95-readiness-drill.json.tmp" "$OUT/day-95-readiness-drill.json"
cat "$OUT/day-95-readiness-drill.json"
printf '\nPASS: readiness fault observed, request sample verified, and /ready restored.\n'
