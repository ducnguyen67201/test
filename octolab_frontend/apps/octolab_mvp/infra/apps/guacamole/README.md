# Guacamole Deployment

Guacamole core deployment (web + guacd + Postgres) in `octolab-system`.

## Prerequisites

G0 completed: k3s, Traefik, cert-manager, namespaces.

## Deployment

From repo root:

```bash
kubectl apply -k infra/apps/guacamole/
```

## Configuration

### Traefik External IP and /etc/hosts

Get Traefik's external IP:

```bash
kubectl get svc -n kube-system traefik
```

Suppose the EXTERNAL-IP is `192.168.0.10`, add to `/etc/hosts`:

```bash
echo "192.168.0.10 guac.octolab.local" | sudo tee -a /etc/hosts
```

### Verify Resources

Check pods, services, ingress, and certificates:

```bash
kubectl get pods -n octolab-system
kubectl get svc -n octolab-system
kubectl get ingress -n octolab-system
kubectl get certificate -n octolab-system
```

## Access

1. Open `https://guac.octolab.local/guacamole/` in a browser
2. Accept self-signed cert warning (dev environment)
3. Default Guacamole admin credentials: `guacadmin` / `guacadmin`

**Note:** 
- Guacamole serves at `/guacamole/` path (not root `/`)
- This is an MVP hack, will be hardened later

## Database Schema Verification

Verify the Guacamole database schema was initialized:

```bash
kubectl exec -n octolab-system guac-db-0 -- \
  psql -U guacamole_user -d guacamole_db -c '\dt'
```

Expected tables: `guacamole_user`, `guacamole_connection`, etc.

## Components

- **guac-web**: Guacamole web application (port 8080)
- **guacd**: Guacamole daemon (port 4822)
- **guac-db**: PostgreSQL database (port 5432)

All components run in the `octolab-system` namespace with resource limits appropriate for a single-node dev cluster.

