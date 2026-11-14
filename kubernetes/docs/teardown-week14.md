# Week 14 teardown — explicit destructive checkpoint

**Deleting `meeps-k8s-cluster` destroys its node containers and node-local PostgreSQL data. A PVC retention policy does not preserve a disk inside a deleted kind node container.** Do not proceed until verification, screenshots, documentation and Git copies are saved. A small local data export is optional; retaining a dump is not proof of a successful restore.

## Optional database export outside Git

Run while PostgreSQL still exists. This captures one database in PostgreSQL custom format, not global roles/passwords. Retain the migrations and role-creation workflow separately. The output can contain data; keep it private.

```bash
(
  set -euo pipefail
  umask 077
  mkdir -p "$HOME/meeps-private-backups"
  chmod 700 "$HOME/meeps-private-backups"
  DUMP="$HOME/meeps-private-backups/week14-$(date +%Y%m%d-%H%M%S).dump"
  kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
    --context kind-meeps-k8s-cluster -n meeps-dev exec postgres-0 -- sh -ec '
      export PGPASSWORD="$POSTGRES_PASSWORD"
      exec pg_dump --host=127.0.0.1 --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" --format=custom --no-owner --no-acl
    ' > "$DUMP.tmp"
  test -s "$DUMP.tmp"
  kubectl --kubeconfig "$HOME/.kube/meeps-k8s-cluster.yaml" \
    --context kind-meeps-k8s-cluster -n meeps-dev exec -i postgres-0 -- \
    pg_restore --list < "$DUMP.tmp" > /dev/null
  mv "$DUMP.tmp" "$DUMP"
  printf 'Private export saved: %s\n' "$DUMP"
)
```

Listing the archive checks readability, not a full restore. Database-global roles are intentionally excluded; a restored application will need its role/permissions setup.

## Before deletion

1. Four failure/recovery results exist and `day-98-final-result.json` passes.
2. Original API records are verified while the cluster still exists.
3. Read the security, diff and validation-scope notes. Review all screenshots/logs.
4. Finish the README and operational documents.
5. Stage and inspect changes, run the index audit, include its generated report, commit and push.
6. `git status --short` must be empty. Stop any port-forward/watch terminals.
7. Decide whether the database needs the private export above.

## Delete only this cluster

With the Day 98 Python environment active:

```bash
python3 kubernetes/scripts/day98-lab.py teardown \
  --confirm DELETE-meeps-k8s-cluster
```

The helper checks the recorded cluster identity, a clean Git tree and the committed final result before deletion. It verifies the named cluster and its labeled node containers are absent. Only after that does it remove:

- `.local/meeps-dev/secret.local.yaml`
- `.local/meeps-dev/api-secret.local.yaml`
- `.env.preflight`, when still present
- `~/.kube/meeps-k8s-cluster.yaml`, the dedicated lab file only

It does not delete `~/.kube/config`, other clusters, the source repository, backups or shared images. Removal of a file is not secure erasure of every copy, snapshot or prior publication. Any additional private files need separate review; no recursive delete of `.local/` is performed.

Verify the result:

```bash
kind get clusters
docker --context desktop-linux ps -a \
  --filter 'label=io.x-k8s.kind.cluster=meeps-k8s-cluster'
cat kubernetes/docs/day-98-teardown-result.json
```

## Optional precise image cleanup

List the four known Week 14 API tags first:

```bash
python3 kubernetes/scripts/day98-lab.py images
```

Only after reviewing that list:

```bash
python3 kubernetes/scripts/day98-lab.py images --remove
```

The helper skips tags used by any existing container and uses no force/global prune. Removing one of several tags can merely untag the shared image. It does not remove registry images, unrelated ECS tags, postgres, Traefik or kind node images. Some image/build cache storage can remain by design.

**Do not run `docker system prune -a --volumes` as a substitute.**

Commit and push the teardown/cleanup reports separately. Future Week 15 work should create fresh configuration and credentials, not reuse the deleted local runtime as a production database.

## References

- https://kind.sigs.k8s.io/docs/user/quick-start/#deleting-a-cluster
- https://www.postgresql.org/docs/15/app-pgdump.html
- https://docs.docker.com/reference/cli/docker/image/rm/
