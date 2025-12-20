> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Local Kubernetes (k3d) Development Setup

This document describes how to set up a local Kubernetes cluster using k3d (k3s-in-Docker) for OctoLab development. This approach solves the WSL kubelet mount parsing crashes that occur with direct k3s deployments in WSL, and enables multiple concurrent labs without port conflicts.

## Why k3d?

Running k3s directly in WSL can cause kubelet crashes due to parsing issues with Docker Desktop's mount format in `/proc/mounts`. Using k3d (k3s-in-Docker) avoids the issue by running the entire k3s cluster as Docker containers, eliminating the need for kubelet to parse WSL-mounted filesystems.

## Prerequisites

- Docker Desktop installed and running with WSL integration enabled
- kubectl command-line tool
- k3d command-line tool

### Installation

```bash
# Install kubectl (Windows via Chocolatey)
choco install kubernetes-cli

# Install k3d (Windows via Chocolatey)
choco install k3d

# OR Install k3d in WSL/Ubuntu:
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
```

Verify installation:
```bash
docker --version     # Should connect to Docker Desktop
kubectl version --client
k3d version
```

## Bootstrap k3d Cluster

To create a k3d cluster for OctoLab development:

```bash
# Navigate to project root
cd /path/to/octolab_mvp

# Run the bootstrap script
./scripts/dev/k3d_bootstrap.sh
```

This script:
- Verifies Docker, kubectl, and k3d are available
- Checks that Docker daemon is responsive
- Creates or starts a k3d cluster named `octolab-dev` with:
  - 1 server node and configurable number of agents (default: 1)
  - API server bound to localhost (`127.0.0.1:6550`) - more secure than 0.0.0.0
  - Automatic kubectl context switching to the new cluster
  - Verification of cluster readiness with nodes

### Configuration Options

Override defaults with environment variables:

- `K3D_CLUSTER_NAME` - Cluster name (default: `octolab-dev`)
- `K3D_API_PORT` - API server port (default: `6550`, bound to 127.0.0.1 only)
- `K3D_AGENTS` - Number of agent nodes (default: `1`)
- `K3D_BIND_HOST` - Bind address (default: `127.0.0.1`)

Example with different configuration:
```bash
K3D_CLUSTER_NAME=my-dev K3D_API_PORT=6551 K3D_AGENTS=2 ./scripts/dev/k3d_bootstrap.sh
```

The script is idempotent - running it multiple times will check for the cluster and start it if needed.

## Using with OctoLab Backend

Once your k3d cluster is running, configure the OctoLab backend to use it:

```bash
# The bootstrap script automatically sets the correct context
kubectl config current-context  # Should show k3d-octolab-dev

# Or explicitly set the context if needed
kubectl config use-context k3d-octolab-dev

# Optional: Export specific context name if different from the default
export KUBECTL_CONTEXT=k3d-octolab-dev

# Then start the backend
python -m uvicorn app.main:app --reload
```

## Verification Commands

Once the cluster is set up, verify functionality:

```bash
# Check kubectl context
kubectl config current-context

# Check nodes
kubectl get nodes

# Check cluster info
kubectl cluster-info

# Check API server health
kubectl get --raw='/readyz'
```

## Teardown

To remove the k3d cluster when no longer needed:

```bash
./scripts/dev/k3d_teardown.sh
```

This will:
- Check if the cluster exists
- Delete only the named cluster (default: `octolab-dev`)
- Leave other k3d clusters untouched
- Switch kubectl context if the deleted one was active

### Using Custom Cluster Names

If you created a cluster with a different name, set the same environment variable for teardown:
```bash
K3D_CLUSTER_NAME=my-dev ./scripts/dev/k3d_teardown.sh
```

## Troubleshooting

### Docker Desktop Not Running
Error: `Cannot connect to the Docker daemon`

Solution: Start Docker Desktop and ensure WSL integration is enabled in Settings > Resources > WSL Integration.

### Port Already in Use
Error: `Bind for 0.0.0.0:6550 failed: port is already allocated`

Solution: Change the port with environment variable:
```bash
K3D_API_PORT=6551 ./scripts/dev/k3d_bootstrap.sh
```

### Context Not Set Properly
If kubectl commands fail with connection errors, verify your context:
```bash
kubectl config current-context  # Should show k3d-octolab-dev or k3d-<your-cluster-name>
kubectl get nodes               # Should return nodes from k3d cluster
```

### WSL Filesystem Tips
- Keep your repository in the Linux filesystem (e.g., `/home/user/octolab_mvp`) rather than Windows mounts (`/mnt/c/...`) to avoid potential I/O issues.

## Security Considerations

- API server binds to localhost only (`127.0.0.1`) by default - more secure than 0.0.0.0
- No auto-installation of packages - explicit installation instructions provided
- All sensitive data (tokens, kubeconfigs) handled securely by k3d and Kubernetes
- Tenant isolation maintained through proper namespace usage

## Benefits of k3d Approach

- **Avoids WSL mount parsing crashes** that occur with direct k3s in WSL
- **Secure localhost-only binding** by default prevents inadvertent exposure
- **Resource efficient** - runs in Docker containers instead of full VMs
- **Fast startup** compared to other Kubernetes solutions
- **Concurrent labs support** - each lab gets unique ports from server-controlled range
- **Isolated kubeconfig** - keeps dev cluster separate from other contexts

This setup provides a stable local Kubernetes development environment that avoids the WSL-specific kubelet crashes while maintaining security and multi-tenant isolation.