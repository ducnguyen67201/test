# Cluster Bootstrap for OctoLab

Single-node k3s cluster setup for OctoLab development on Ubuntu 22.04.

## Prerequisites

- Ubuntu 22.04 LTS
- Root or sudo access
- `curl` installed
- 2GB+ RAM, 20GB+ disk space
- Internet access

## Quick Start

1. **Clone the repository** (if not already done):
   ```bash
   cd /path/to/octolab_mvp
   ```

2. **Install k3s** (as root or with sudo):
   ```bash
   sudo bash infra/cluster/install-k3s.sh
   ```

3. **Verify the cluster** (as your normal user):
   ```bash
   bash infra/cluster/verify-cluster.sh
   ```

## What This Does

- Installs k3s with **Traefik disabled** (we'll install our own via Helm)
- Configures kubeconfig at `~/.kube/config` for your user
- Verifies the cluster is healthy

## Notes

- k3s is installed with `--disable=traefik` to avoid conflicts with our Helm-installed Traefik
- kubeconfig is automatically copied to `~/.kube/config` with correct permissions
- The cluster runs as a systemd service: `k3s.service`

## Troubleshooting

### kubectl command not found

If `kubectl` is not in your PATH, you can:
- Use k3s's bundled kubectl: `/usr/local/bin/kubectl`
- Install kubectl separately: https://kubernetes.io/docs/tasks/tools/

### kubectl get nodes fails

Check the k3s service status:
```bash
sudo systemctl status k3s
```

If the service is not running:
```bash
sudo systemctl start k3s
sudo systemctl enable k3s
```

### Permission denied on kubeconfig

The verify script should handle this automatically, but if you see permission errors:
```bash
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
```

## Next Steps

After cluster bootstrap, continue with:
- Installing Helm (see `docs/infra/cluster-setup.md`)
- Installing Traefik ingress controller
- Installing cert-manager
- Creating namespaces

See `docs/infra/cluster-setup.md` for the complete setup guide.

