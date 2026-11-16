# Day 92 — Kubernetes Mental Model and Local Cluster

## What I Did
- Verified Docker Desktop and checked my Intel Mac's available CPU, memory and disk space.
- Installed `kind v0.33.0` in `~/meeps-tools/bin` and verified its SHA-256 checksum.
- Updated my terminal's `PATH` and confirmed `kind` and the existing `kubectl v1.36.1` were available.
- Reviewed the configuration for `meeps-k8s-cluster`: one control-plane node, two workers, and loopback HTTP/HTTPS port mappings.

## What I Learnt
- Kubernetes reconciles actual state with the desired state declared in manifests.
- The control plane coordinates the cluster; worker nodes run application Pods.
- `kind` creates local clusters, `kubectl` manages resources, and Kustomize customizes manifests. The Kustomize version displayed by `kubectl` is embedded tooling.
- Kubeconfig holds connection settings; a context selects the cluster, user and namespace.
- Labels group/select objects; annotations store additional metadata.
- Pod Security `audit` and `warn` report policy violations without blocking Pods; they are not enforcement.

## What Broke and How I Fixed It
- **Failure:** `mkdir: /Users/user/.local/share: Permission denied` stopped the installer before downloading `kind`.
- **Fix:** Installed into the writable `~/meeps-tools/bin` directory instead, without using `sudo` or changing permissions on `.local`.
- **Verification:** The checksum passed, `command -v kind` resolved the new location, and `kind version` succeeded.

## Completion Checks
The shared output confirms the toolchain fix; the remaining cluster results still need confirmation.

- [ ] All three nodes are `Ready`, and system Pods are healthy.
- [ ] Current context is `kind-meeps-k8s-cluster`; default namespace is `meeps-dev`.
- [ ] Namespace labels and Pod Security audit/warn settings are applied.
- [ ] Configuration, foundational commands and verification evidence are saved; kubeconfig remains outside Git.

**Scope:** Day 92 foundations only; application and database deployment belong to later sessions.
