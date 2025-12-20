> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Cluster Setup Guide

End-to-end guide for setting up a single-node k3s cluster for OctoLab development.

## Overview

This guide walks through setting up a **single-node k3s cluster** on Ubuntu 22.04 with:
- Traefik ingress controller (installed via Helm)
- cert-manager for TLS certificate management
- Base namespaces for OctoLab components

## Prerequisites

- **OS**: Ubuntu 22.04 LTS
- **Resources**: 2-4GB RAM, 20GB+ disk space
- **Access**: Root or sudo access
- **Network**: Internet access for downloading packages and container images

## Step 1: Install k3s

Run the k3s installation script:

```bash
sudo bash infra/cluster/install-k3s.sh
```

This installs k3s with:
- Built-in Traefik **disabled** (we'll install our own)
- Kubeconfig mode set to 644 (readable by all users)

**Expected output:**
- k3s service starts automatically
- Kubeconfig created at `/etc/rancher/k3s/k3s.yaml`

## Step 2: Verify Cluster

Run the verification script as your normal user:

```bash
bash infra/cluster/verify-cluster.sh
```

This script:
- Copies kubeconfig to `~/.kube/config`
- Verifies cluster connectivity
- Shows cluster status

**Expected output:**
- One node in "Ready" state
- Core system pods running (coredns, local-path-provisioner, etc.)

## Step 3: Install Helm

Install Helm 3 (required for Traefik and cert-manager):

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Verify installation:

```bash
helm version
```

## Step 4: Install Traefik Ingress Controller

Add Traefik Helm repository and install:

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update

helm install traefik traefik/traefik \
  --namespace kube-system \
  --create-namespace \
  --values infra/base/ingress/values-traefik.yaml
```

Verify Traefik is running:

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get svc -n kube-system traefik
```

**Expected:**
- Traefik pod in "Running" state
- Service exposing ports 80 and 443

## Step 5: Install cert-manager

Add cert-manager Helm repository and install:

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --values infra/base/cert-manager/values-cert-manager.yaml
```

Wait for cert-manager to be ready:

```bash
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance=cert-manager \
  -n cert-manager \
  --timeout=300s
```

Apply the self-signed ClusterIssuer:

```bash
kubectl apply -f infra/base/cert-manager/self-signed-issuer.yaml
```

Verify:

```bash
kubectl get clusterissuer self-signed
```

## Step 6: Create Namespaces

Create the base namespaces for OctoLab:

```bash
kubectl apply -k infra/base/namespaces/
```

Verify namespaces:

```bash
kubectl get namespaces | grep octolab
```

**Expected:**
- `octolab-system` namespace
- `octolab-labs` namespace

## Step 7: Quick Sanity Check

Run a final verification:

```bash
# Check all namespaces
kubectl get ns

# Check all pods across namespaces
kubectl get pods -A

# Check Traefik service
kubectl get svc -n kube-system traefik

# Check cert-manager ClusterIssuer
kubectl get clusterissuer
```

**Healthy cluster should show:**
- `octolab-system` and `octolab-labs` namespaces exist
- Traefik pod running in `kube-system`
- cert-manager pods running in `cert-manager`
- `self-signed` ClusterIssuer exists

## Troubleshooting

### k3s service not running

```bash
sudo systemctl status k3s
sudo systemctl start k3s
sudo journalctl -u k3s -f
```

### Traefik pod not starting

```bash
kubectl describe pod -n kube-system -l app.kubernetes.io/name=traefik
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik
```

### cert-manager webhook issues

```bash
kubectl get pods -n cert-manager
kubectl describe pod -n cert-manager -l app.kubernetes.io/component=webhook
```

### kubectl permission errors

Ensure kubeconfig has correct permissions:

```bash
ls -la ~/.kube/config
# Should show your user as owner
```

If not, fix permissions:

```bash
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
```

## Next Steps

After completing this setup:

1. **G1 Slice**: Deploy Guacamole (webapp + guacd + database)
2. **G2 Slice**: Deploy OctoLab backend API and database
3. **G3 Slice**: Implement KubernetesLabRuntime for dynamic lab provisioning

See `docs/infra/architecture.md` for the overall architecture.

