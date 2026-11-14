# kubectl reference — Week 14

Run from the repository root and activate the lab session in each terminal. Never publish kubeconfig, `get secret -o yaml`, decoded values, or unreviewed logs.

```bash
source kubernetes/scripts/use-local-cluster.sh
kubectl config current-context
kubectl cluster-info
kubectl get nodes -o wide
kubectl get pods -A
kubectl api-resources
kubectl explain deployment.spec
```

## Workload and routing inspection

```bash
kubectl -n meeps-dev get deployment,replicaset,pods -o wide
kubectl -n meeps-dev get svc,ingress,endpointslice
kubectl -n meeps-dev describe pod <pod-name>
kubectl -n meeps-dev get events --sort-by=.metadata.creationTimestamp
kubectl -n meeps-dev logs <pod-name> -c api --tail=40
kubectl -n meeps-dev logs <pod-name> -c api --previous
kubectl -n meeps-dev get endpointslice -l kubernetes.io/service-name=meeps-api -o yaml
kubectl -n meeps-dev port-forward --address 127.0.0.1 service/meeps-api 18000:80
```

Port-forward chooses a backend Pod and is not proof of ClusterIP load balancing or Ingress behavior. Previous logs apply to a restarted container; a container that never started has no application log to inspect.

## Declarative validation

```bash
kubectl apply --dry-run=server --validate=strict -f kubernetes/base/api-service.yaml
kubectl diff -f kubernetes/base/api-service.yaml
```

Diff exits 0 for no change, 1 for differences, and greater than 1 for an error. Never blindly apply the full repository; examples, patches, Secrets, kind config and historical captures have different validation scopes. After HPA handoff, the current API manifest must not contain `spec.replicas`.

## Rollouts, autoscaling and storage

```bash
kubectl -n meeps-dev rollout status deployment/meeps-api --timeout=180s
kubectl -n meeps-dev rollout history deployment/meeps-api
kubectl -n meeps-dev get hpa,pdb
kubectl -n meeps-dev describe hpa meeps-api
kubectl top nodes
kubectl -n meeps-dev top pods --containers
kubectl -n meeps-dev get statefulset,pvc
kubectl -n meeps-dev logs job/meeps-db-migrate-day93
```

The completed migration Job may have been removed by its TTL. Absence is not a reason to recreate it during final validation.

Historical manual scaling example **before HPA only**: `kubectl -n meeps-dev scale deployment/meeps-api --current-replicas=2 --replicas=4`.

For rollback, select a verified retained revision with `kubectl -n meeps-dev rollout undo deployment/meeps-api --to-revision=<number>`. Reconcile the current tracked Pod template afterward; do not blindly apply old fixed-replica manifests while HPA controls scaling.

## Maintenance

A normal drain respects eviction/PDB checks. Use the guarded Day 97 script to exclude PostgreSQL's worker. Do not use `--force` or `--disable-eviction` to conceal a blocked exercise. `kubectl uncordon <worker>` re-enables scheduling but does not move running Pods.

## Sources

- https://kubernetes.io/docs/reference/kubectl/
- https://kubernetes.io/docs/reference/kubectl/generated/kubectl_diff/
- https://kubernetes.io/docs/reference/kubectl/generated/kubectl_logs/
