> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Docker Address Pool Exhaustion

This document covers Docker subnet exhaustion, diagnosis, and recovery procedures for OctoLab operators.

## Background

Docker allocates IP subnets from a default address pool (typically `172.17-31.0.0/16`) for each bridge network. Each `docker-compose` project creates at least one network, consuming one or more `/16` subnets. With only ~15 available subnets in the default pool, running many labs concurrently can exhaust the pool.

When exhausted, Docker reports errors like:
- `could not find an available, non-overlapping IPv4 address pool`
- `pool overlaps with other one on this address space`

## Automatic Recovery

OctoLab includes automatic preflight cleanup that runs before each lab creation:

1. **Prune unused networks**: Calls `docker network prune` to remove networks with no attached containers
2. **Scoped cleanup**: Lists `octolab_*` networks and removes those with no containers
3. **Allowlist-based forced disconnect**: For networks with attached containers, force-disconnects containers that are in the `CONTROL_PLANE_CONTAINERS` allowlist (default: `["octolab-guacd"]`)

This is best-effort and non-blocking - if cleanup fails, lab creation continues and may fail with a clear error.

## Manual Recovery Procedures

### Quick Recovery (Safe)

```bash
# Prune all unused networks (safe - only removes networks with no containers)
docker network prune -f

# List remaining octolab networks
docker network ls --filter 'name=octolab_'
```

### Identify Blocked Networks

```bash
# Show what containers are attached to each network
for net in $(docker network ls --filter 'name=octolab_' --format '{{.Name}}'); do
    echo "=== $net ==="
    docker network inspect --format '{{range .Containers}}{{.Name}} {{end}}' "$net"
done
```

### Force Cleanup Stale Networks

If you find networks with stale containers (e.g., orphaned lab containers that weren't cleaned up):

```bash
# Force-disconnect all containers from a specific network
NETWORK=octolab_<lab-id>_lab_net
for container in $(docker network inspect --format '{{range .Containers}}{{.Name}} {{end}}' $NETWORK); do
    docker network disconnect -f $NETWORK $container
done
docker network rm $NETWORK
```

### Nuclear Option (Development Only)

**WARNING**: This will affect ALL Docker networks including other projects.

```bash
# Stop all containers
docker stop $(docker ps -q)

# Remove all containers
docker rm $(docker ps -aq)

# Prune all networks
docker network prune -f
```

## Expanding the Address Pool (Production)

For production environments with many concurrent labs, expand Docker's default address pool in `/etc/docker/daemon.json`:

```json
{
  "default-address-pools": [
    {
      "base": "172.16.0.0/12",
      "size": 24
    },
    {
      "base": "10.200.0.0/14",
      "size": 24
    }
  ]
}
```

This configuration:
- Uses `/24` subnets instead of `/16` (254 hosts per network vs 65k)
- Provides ~4000 networks in the 172.16.0.0/12 range
- Adds 10.200.0.0/14 as overflow (~1000 more networks)

After editing, restart Docker:
```bash
sudo systemctl restart docker
```

**Note**: Restarting Docker will stop all running containers.

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTROL_PLANE_CONTAINERS` | `["octolab-guacd"]` | Container names that can be force-disconnected from stale networks |
| `DOCKER_NETWORK_TIMEOUT_SECONDS` | `30` | Timeout for docker network operations |

### Adjusting the Allowlist

To add additional containers to the force-disconnect allowlist:

```bash
# In .env.local
CONTROL_PLANE_CONTAINERS='["octolab-guacd", "octolab-db"]'
```

**Security**: Only add containers you control (control-plane services). Never add user lab containers - they should be torn down via the normal lab lifecycle.

## Monitoring

### Check Current Network Count

```bash
# Total Docker networks
docker network ls | wc -l

# OctoLab networks specifically
docker network ls --filter 'name=octolab_' | wc -l
```

### Alert Thresholds

Consider alerting when:
- Total Docker networks exceed 80% of pool capacity
- OctoLab networks exceed expected concurrent lab count by 2x
- Labs repeatedly fail with "pool exhausted" errors

## Troubleshooting

### Lab Creation Fails with "pool exhausted"

1. Check OctoLab logs for cleanup results:
   ```
   Network cleanup: pruned=X, disconnected=Y, removed=Z, blocked=W
   ```

2. If `blocked > 0`, networks have non-allowlisted containers attached
   - Identify the containers (see "Identify Blocked Networks" above)
   - If they're orphaned lab containers, stop them manually
   - If they're from another project, either stop that project or expand the address pool

3. If cleanup reports success but creation still fails:
   - Pool may be genuinely exhausted (non-OctoLab networks)
   - Consider expanding the address pool

### guacd Can't Connect to Lab

If guacd was disconnected during cleanup and can't reconnect:

```bash
# Reconnect guacd to a lab's network
docker network connect octolab_<lab-id>_lab_net octolab-guacd
```

The lab provisioner will automatically reconnect guacd, but manual reconnection may be needed if cleanup happened mid-operation.
