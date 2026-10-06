#!/usr/bin/env bash
# First-time local-lab provisioning only. Review before running.
# Requires the completed Day 93 PostgreSQL setup and an active lab session.
set +x
set -euo pipefail
umask 077

fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
[ "$(kubectl config current-context)" = "kind-meeps-k8s-cluster" ] || fail "Wrong Kubernetes context."
[ -f kubernetes/scripts/api-runtime-grants.sql ] || fail "Run from the repository root."
[ -f kubernetes/base/postgres-statefulset.yaml ] || fail "Day 93 files are missing."

k() { kubectl --context kind-meeps-k8s-cluster --namespace meeps-dev "$@"; }
db_admin() {
  k exec -i postgres-0 -c postgres -- sh -ec '
    export PGPASSWORD="$POSTGRES_PASSWORD"
    exec psql -X --no-password --host=127.0.0.1 \
      --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
      --set=ON_ERROR_STOP=1 "$@"
  ' sh "$@"
}

PRIVATE_DIR=".local/meeps-dev"
SECRET_FILE="$PRIVATE_DIR/api-secret.local.yaml"
[ -z "$(git ls-files -- .local/)" ] || fail "Git tracks files under .local; review them first."
git check-ignore --quiet --no-index "$SECRET_FILE" || fail "Add /.local/ to .gitignore first."
[ ! -e "$SECRET_FILE" ] || fail "The local API Secret already exists. Do not regenerate it."
[ -z "$(k get secret meeps-api-credentials --ignore-not-found -o name)" ] || fail "The API Secret already exists in the cluster."
[ "$(db_admin -Atc "SELECT count(*) FROM pg_roles WHERE rolname = 'meeps_api';")" = "0" ] || fail "The runtime role already exists. Inspect/recover credentials instead of rotating them."
[ "$(db_admin -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('users','posts','alembic_version');")" = "3" ] || fail "Day 93 tables are missing."

DB_NAME="$(k get configmap meeps-db-config -o jsonpath='{.data.POSTGRES_DB}')"
DB_HOST="$(k get configmap meeps-db-config -o jsonpath='{.data.POSTGRES_HOST}')"
DB_PORT="$(k get configmap meeps-db-config -o jsonpath='{.data.POSTGRES_PORT}')"
[ "$DB_NAME" = "meeps_users_posts" ] || fail "Unexpected database name; review the Day 93 configuration."
[ "$DB_HOST" = "postgres" ] || fail "Unexpected database host."
[ "$DB_PORT" = "5432" ] || fail "Unexpected database port."

mkdir -p "$PRIVATE_DIR"
chmod 700 "$PRIVATE_DIR"
WORK_DIR="$(mktemp -d "$PRIVATE_DIR/.api-provision.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
PASSWORD="$(openssl rand -hex 24)"
case "$PASSWORD" in *[!0-9a-f]*|'') fail "Invalid generated password." ;; esac
[ "${#PASSWORD}" = "48" ] || fail "Unexpected password length."

printf 'postgresql://meeps_api:%s@%s:%s/%s' \
  "$PASSWORD" "$DB_HOST" "$DB_PORT" "$DB_NAME" > "$WORK_DIR/database-url"
k create secret generic meeps-api-credentials \
  --from-file=DATABASE_URL="$WORK_DIR/database-url" \
  --dry-run=client -o yaml > "$WORK_DIR/secret.yaml"

# Save credentials before activating the database role so partial failures
# never require guessing or regenerating the original password.
install -m 0600 "$WORK_DIR/secret.yaml" "$SECRET_FILE"

{
  printf 'BEGIN;\n'
  printf "CREATE ROLE meeps_api WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '%s';\n" "$PASSWORD"
  cat kubernetes/scripts/api-runtime-grants.sql
  printf '\nCOMMIT;\n'
} > "$WORK_DIR/provision.sql"
unset PASSWORD

db_admin < "$WORK_DIR/provision.sql"
k apply --server-side --field-manager=meeps-local-api-secrets -f "$SECRET_FILE"
k get secret meeps-api-credentials
printf 'Runtime role and API Secret created. No credential values were printed.\n'
printf 'Keep %s local and untracked. This helper deliberately refuses automatic reruns.\n' "$SECRET_FILE"
