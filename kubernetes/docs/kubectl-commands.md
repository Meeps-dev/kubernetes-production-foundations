# Kubernetes command reference — Day 92

Run these commands from the repository root.

## Activate the local lab session

```bash

source kubernetes/scripts/use-local-cluster.sh

### Inspect tools and cluster connections

kind version
kind get clusters
kubectl version
kubectl config current-context
kubectl config get-contexts
kubectl cluster-info

### Inspect nodes and system workloads

kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl get deployments,daemonsets -n kube-system
kubectl get storageclass
kubectl get events -A --sort-by=.metadata.creationTimestamp

### Inspect API resource types and their fields

kubectl api-resources
kubectl explain namespace
kubectl explain deployment.spec

### Validate and apply the namespace declaration

kubectl apply --dry-run=server -f kubernetes/base/namespace.yaml
kubectl apply -f kubernetes/base/namespace.yaml
kubectl get namespace meeps-dev --show-labels
kubectl describe namespace meeps-dev

### Select the default namespace

kubectl config set-context kind-meeps-k8s-cluster --namespace=meeps-dev

### Wait for readiness

kubectl wait --for=condition=Ready nodes --all --timeout=180s
kubectl wait -n kube-system --for=condition=Ready pods --all --timeout=180s

### Configuration decisions

- Cluster: meeps-k8s-cluster.
- Context: kind-meeps-k8s-cluster.
- Namespace: meeps-dev.
- One control-plane node and two workers.
- kubeconfig is stored outside the repository.
- HTTP mapping: 127.0.0.1:8080 to node port 30080.
- HTTPS mapping: 127.0.0.1:8443 to node port 30443.
- Future ingress NodePorts must match these mappings.
- Port mappings alone do not provide HTTP routing or TLS.
- Pod Security audit/warn use Restricted v1.37; enforcement is not enabled.
- Application and database deployment are outside Day 92.