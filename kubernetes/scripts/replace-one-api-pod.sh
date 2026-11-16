#!/usr/bin/env bash
# Delete exactly one API Pod and record its replacement.
set -euo pipefail

[ "$(kubectl config current-context)" = "kind-meeps-k8s-cluster" ] || {
  printf 'STOP: Wrong Kubernetes context.\n' >&2
  exit 1
}

[ -f kubernetes/base/api-deployment.yaml ] || {
  printf 'STOP: Run from the repository root.\n' >&2
  exit 1
}

k() {
  kubectl --context kind-meeps-k8s-cluster \
    --namespace meeps-dev "$@"
}

SELECTOR='app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev'
OUT='kubernetes/docs'

mkdir -p "$OUT"

[ ! -e "$OUT/day-94-replacement-pod.txt" ] || {
  printf 'STOP: A saved replacement already exists. Continue with verification.\n' >&2
  exit 1
}

[ -s "$OUT/day-94-fixture.json" ] || {
  printf 'STOP: First save a successful create/read fixture.\n' >&2
  exit 1
}

# Confirm that the original records are readable before deleting anything.
k exec -i deployment/meeps-api -c api -- \
  python - verify \
    --base-url http://meeps-api \
    --fixture-json "$(cat "$OUT/day-94-fixture.json")" \
  < kubernetes/scripts/api-smoke-test.py \
  > /dev/null

k rollout status deployment/meeps-api --timeout=180s

[ "$(k get deployment meeps-api -o jsonpath='{.spec.replicas}')" = "2" ]
[ "$(k get deployment meeps-api -o jsonpath='{.status.availableReplicas}')" = "2" ]

k get pods -l "$SELECTOR" -o json \
  > "$OUT/day-94-pods-before.json"

k get pods -l "$SELECTOR" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
  | LC_ALL=C sort > "$OUT/day-94-pod-names-before.txt"

[ "$(wc -l < "$OUT/day-94-pod-names-before.txt" | tr -d ' ')" = "2" ] || {
  printf 'STOP: Expected exactly two API Pods before the test.\n' >&2
  exit 1
}

VICTIM="$(head -n 1 "$OUT/day-94-pod-names-before.txt")"
OWNER="$(k get pod "$VICTIM" -o jsonpath='{.metadata.ownerReferences[0].name}')"

printf 'Deleting one API Pod: %s (ReplicaSet: %s)\n' "$VICTIM" "$OWNER"

k delete pod "$VICTIM" --wait=true --timeout=90s

NEW_POD=''

for ATTEMPT in {1..60}; do
  k get pods -l "$SELECTOR" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | LC_ALL=C sort > "$OUT/day-94-pod-names-current.txt"

  NEW_POD="$(LC_ALL=C comm -13 \
    "$OUT/day-94-pod-names-before.txt" \
    "$OUT/day-94-pod-names-current.txt")"

  [ -n "$NEW_POD" ] && break
  sleep 2
done

[ -n "$NEW_POD" ] || {
  printf 'STOP: No replacement Pod appeared.\n' >&2
  exit 1
}

[ "$(printf '%s\n' "$NEW_POD" | wc -l | tr -d ' ')" = "1" ] || {
  printf 'STOP: Multiple new Pods appeared; inspect before continuing.\n' >&2
  exit 1
}

k wait --for=condition=Ready "pod/$NEW_POD" --timeout=180s
k rollout status deployment/meeps-api --timeout=180s

NEW_OWNER="$(k get pod "$NEW_POD" -o jsonpath='{.metadata.ownerReferences[0].name}')"

[ "$NEW_OWNER" = "$OWNER" ] || {
  printf 'STOP: ReplicaSet changed; investigate a concurrent rollout.\n' >&2
  exit 1
}

[ "$(k get deployment meeps-api -o jsonpath='{.status.availableReplicas}')" = "2" ]

k get pods -l "$SELECTOR" -o json \
  > "$OUT/day-94-pods-after.json"

printf '%s\n' "$NEW_POD" \
  > "$OUT/day-94-replacement-pod.txt"

printf 'Replaced Pod: %s\nReplacement Pod: %s\nReplicaSet unchanged: %s\n' \
  "$VICTIM" "$NEW_POD" "$OWNER" \
  | tee "$OUT/day-94-replacement-result.txt"

k get pods -l "$SELECTOR" -o wide
