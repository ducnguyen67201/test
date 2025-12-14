# cert-manager Configuration

cert-manager provides automatic TLS certificate management for the OctoLab cluster.

## Installation

Assuming you are at the repository root and Helm is installed:

```bash
# Add cert-manager Helm repository
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Install cert-manager
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --values infra/base/cert-manager/values-cert-manager.yaml
```

## Wait for cert-manager to be Ready

After installation, wait for cert-manager pods to be ready:

```bash
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance=cert-manager \
  -n cert-manager \
  --timeout=300s
```

## Apply Self-Signed ClusterIssuer

For development, apply the self-signed ClusterIssuer:

```bash
kubectl apply -f infra/base/cert-manager/self-signed-issuer.yaml
```

Verify the ClusterIssuer:

```bash
kubectl get clusterissuer self-signed
```

## Usage in Ingress Resources

To use the self-signed issuer in an Ingress resource, add this annotation:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: self-signed
```

## Future: Let's Encrypt

A future slice will introduce a Let's Encrypt ClusterIssuer with HTTP-01 or DNS-01 challenge configuration for production TLS certificates.

## Notes

- This is MVP/dev TLS using self-signed certificates
- Browser warnings for self-signed certs are expected in development
- For production, we will configure Let's Encrypt with proper domain validation

