# k3d Local Kubernetes Harness

This directory contains k3d configuration and scripts for running a local Kubernetes cluster for OctoLab development.

## Prerequisites

- **Linux/WSL environment**: This setup is designed for Linux or WSL (Windows Subsystem for Linux)
- **Docker**: k3d runs Kubernetes in Docker containers
- **k3d**: Install from https://k3d.io/

```bash
# Install k3d (Linux/WSL)
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
```

## ⚠️ Important: Linux/WSL Filesystem Requirements

**DO NOT run k3d from Windows filesystem mounts** (e.g., `/mnt/c/`, `C:\`, or `\\wsl$\`).

The OctoLab repository MUST live on the native Linux filesystem (e.g., `/home/<user>/octolab_mvp/`) for k3d development because:

1. **Path mapping issues**: k3d/Docker bind mounts don't work reliably across WSL<->Windows boundaries
2. **Performance**: Windows filesystem access from WSL is significantly slower
3. **Permissions**: File permission models differ between Windows and Linux filesystems
4. **Symlinks**: May not work correctly on Windows mounts

### Verify your setup

```bash
# Good: repo on Linux filesystem
$ pwd
/home/architect/octolab_mvp

# Bad: repo on Windows filesystem mount
$ pwd
/mnt/c/Users/architect/projects/octolab_mvp  # ❌ DO NOT USE
```

If your repo is on a Windows mount, clone it to your Linux home directory:

```bash
cd ~
git clone <your-repo-url> octolab_mvp
cd octolab_mvp
```

## Quick Start

```bash
# From repository root
make k3d-up        # Create cluster
make k3d-smoke     # Verify cluster health
make k3d-down      # Delete cluster
```

Or use scripts directly:

```bash
# From infra/k3d directory
./create_cluster.sh
./smoke_test.sh
./delete_cluster.sh
```

## Cluster Configuration

The cluster is defined in `cluster.yaml`:

- **Name**: `octolab-dev` (deterministic for easy scripting)
- **Servers**: 1 control plane node
- **Agents**: 0 worker nodes (can add more for testing)
- **Ingress**: Exposed only to localhost for security
  - HTTP: `127.0.0.1:8080` → port 80 in cluster
  - HTTPS: `127.0.0.1:8443` → port 443 in cluster
- **Network**: No database ports exposed to host (security by default)

### Security Design

- All external-facing services bind to `127.0.0.1` only (deny-by-default)
- No database ports exposed outside k3d network
- Network policies enforce default-deny in `octolab-labs` namespace
- Only DNS egress is allowed by default

## Cluster Management

### Create Cluster

```bash
./create_cluster.sh
# or
make k3d-up
```

Creates the `octolab-dev` cluster if it doesn't exist. Idempotent (safe to run multiple times).

### Verify Cluster

```bash
./smoke_test.sh
# or
make k3d-smoke
```

Checks:
- Cluster is running
- Required namespaces exist (`octolab-system`, `octolab-labs`)
- Nodes are ready
- Basic pod operations work

### Delete Cluster

```bash
./delete_cluster.sh
# or
make k3d-down
```

Removes the `octolab-dev` cluster. Tolerates missing cluster (idempotent).

### Import Local Images

```bash
make k3d-import-image IMAGE=octolab-backend:latest
make k3d-import-image IMAGE=octobox-beta:dev
```

Imports locally built Docker images into the k3d cluster without needing a registry.

## Working with the Cluster

### Access kubectl

```bash
# k3d automatically configures kubectl
kubectl config use-context k3d-octolab-dev
kubectl get nodes
kubectl get namespaces
```

### Deploy OctoLab Components

```bash
# Apply base manifests (namespaces, network policies)
kubectl apply -k infra/base/namespaces/
kubectl apply -k infra/k8s/networkpolicies/

# Deploy applications (when ready)
kubectl apply -k infra/apps/
```

### View Logs

```bash
# Backend logs
kubectl logs -n octolab-system deployment/octolab-backend -f

# Lab pod logs
kubectl logs -n octolab-labs <pod-name> -f
```

### Access Services

Since ingress is bound to localhost:

```bash
# Health check (if deployed)
curl http://127.0.0.1:8080/health

# API endpoints
curl http://127.0.0.1:8080/api/v1/...
```

### Port Forwarding

For services not exposed via ingress:

```bash
# Forward PostgreSQL (if needed for debugging)
kubectl port-forward -n octolab-system service/postgres 5432:5432

# Forward backend directly
kubectl port-forward -n octolab-system deployment/octolab-backend 8000:8000
```

## Troubleshooting

### Cluster won't start

```bash
# Check Docker is running
docker ps

# Check k3d version
k3d version

# View k3d logs
docker logs k3d-octolab-dev-server-0
```

### Network policy issues

```bash
# Check network policies
kubectl get networkpolicies -n octolab-labs

# Describe specific policy
kubectl describe networkpolicy default-deny -n octolab-labs

# Test connectivity from a pod
kubectl run -n octolab-labs test --image=busybox --rm -it -- sh
# Inside pod: wget -O- http://service-name:port
```

### Images not available

```bash
# Import image into cluster
k3d image import octolab-backend:latest -c octolab-dev

# Or use Makefile target
make k3d-import-image IMAGE=octolab-backend:latest
```

### Port conflicts

If ports 8080 or 8443 are already in use:

```bash
# Find what's using the port
sudo lsof -i :8080
sudo lsof -i :8443

# Kill the process or edit cluster.yaml to use different ports
```

## Development Workflow

1. **Start cluster**: `make k3d-up`
2. **Build images locally**: `docker build -t octolab-backend:latest backend/`
3. **Import to k3d**: `make k3d-import-image IMAGE=octolab-backend:latest`
4. **Deploy/update**: `kubectl apply -k infra/apps/`
5. **Test changes**: Access via `http://127.0.0.1:8080`
6. **View logs**: `kubectl logs ...`
7. **Iterate**: Rebuild → Import → Redeploy

## Cleanup

```bash
# Delete cluster
make k3d-down

# Remove all k3d clusters (if you have multiple)
k3d cluster delete --all

# Clean up Docker resources
docker system prune -f
```

## CI/CD Notes

This k3d setup is for local development only. For CI:

- Use matrix testing with real Kubernetes versions
- Consider kind or minikube as alternatives
- Set different cluster names to avoid conflicts
- Use ephemeral clusters (create → test → delete)

## References

- k3d documentation: https://k3d.io/
- k3s documentation: https://k3s.io/
- Kubernetes documentation: https://kubernetes.io/docs/
