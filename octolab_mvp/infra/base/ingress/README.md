# Traefik Ingress Controller

Traefik is installed as the primary ingress controller for the OctoLab cluster.

## Installation

Assuming you are at the repository root and Helm is installed:

```bash
# Add Traefik Helm repository
helm repo add traefik https://traefik.github.io/charts
helm repo update

# Install Traefik
helm install traefik traefik/traefik \
  --namespace kube-system \
  --create-namespace \
  --values infra/base/ingress/values-traefik.yaml
```

## Verification

After installation, verify Traefik is running:

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get svc -n kube-system traefik
```

## Configuration

The current configuration (`values-traefik.yaml`) is minimal and includes:

- HTTP (port 80) and HTTPS (port 443) entrypoints
- Default ingress class named `traefik`
- Basic logging enabled
- Dashboard enabled (for debugging)

## Future Enhancements

In later slices, we will add:

- Middleware for HTTP -> HTTPS redirection
- WebSocket configuration (for Guacamole)
- Request size limits
- Additional security headers
- Dashboard authentication

## Notes

- Traefik is installed in the `kube-system` namespace (standard location for ingress controllers)
- The ingress class `traefik` is set as the default, so Ingress resources don't need to specify `ingressClassName` explicitly
- For production, consider moving Traefik to `octolab-system` namespace and securing the dashboard

