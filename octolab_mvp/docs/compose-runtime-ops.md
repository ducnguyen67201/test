# Compose Runtime Operations Guide

This document covers operational tasks for the Docker Compose lab runtime.

## Docker Network Pool Exhaustion

### Symptom

Lab creation fails with errors like:
- "all predefined address pools have been fully subnetted"
- "could not find an available, non-overlapping ipv4 address pool"
- "pool overlaps with other one on this address space"

The backend logs will show:
```
Docker network pool exhausted while creating lab <uuid>.
Network counts: total=<N>, octolab=<M>
```

### Cause

Each Docker Compose lab creates two bridge networks (`lab_net` and `egress_net`).
Docker's default address pool is limited (typically 172.17-31.x.x /16 subnets).
When all subnets are allocated, new labs cannot be created.

**Key insight: Subnet reuse happens when networks are removed.**

Docker allocates a /24 (or configured size) subnet from the address pool when creating
a bridge network. There is no separate "mark subnet reusable" operation—subnets return
to the pool when their networks are deleted via `docker network rm`.

Common causes:
1. **Leaked networks**: Lab networks not cleaned up due to failed teardowns
2. **High concurrent usage**: Many active labs consuming available subnets
3. **Small default pool**: Docker's default pool is too small for the workload

### Admin API Cleanup (Recommended)

Use the admin cleanup endpoint to safely remove leaked networks:

```bash
# Check current network status
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/admin/maintenance/network-status

# Run cleanup (requires admin email in OCTOLAB_ADMIN_EMAILS)
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true, "remove_stopped_containers": true}' \
  http://localhost:8000/admin/maintenance/cleanup-networks
```

**Guardrails:**
- Requires admin authorization (email in `OCTOLAB_ADMIN_EMAILS` env var)
- Requires explicit confirmation (`confirm: true` or `X-Confirm: true` header)
- **REFUSES** if any OctoLab containers are running (409 Conflict)
- Only removes networks matching strict lab pattern (`octolab_<uuid>_(lab_net|egress_net)`)
- Never runs `docker network prune` or `docker system prune`

**Configuration:**
```bash
# In .env.local
OCTOLAB_ADMIN_EMAILS=admin@example.com,ops@example.com
```

### Safe Manual Cleanup (CLI)

If the admin API is not available, you can clean up manually via CLI.

**Only clean up octolab_* networks with 0 attached containers.**

1. List octolab networks and their container counts:
   ```bash
   for net in $(docker network ls --format '{{.Name}}' | grep -E '^octolab_[0-9a-f-]+_(lab_net|egress_net)$'); do
     count=$(docker network inspect -f '{{len .Containers}}' "$net" 2>/dev/null || echo "?")
     echo "$net containers=$count"
   done
   ```

2. Remove empty networks (containers=0):
   ```bash
   for net in $(docker network ls --format '{{.Name}}' | grep -E '^octolab_[0-9a-f-]+_(lab_net|egress_net)$'); do
     count=$(docker network inspect -f '{{len .Containers}}' "$net" 2>/dev/null || echo "1")
     if [ "$count" = "0" ]; then
       echo "Removing empty network: $net"
       docker network rm "$net" 2>/dev/null || true
     fi
   done
   ```

3. **Never run** `docker network prune` or `docker system prune` automatically.
   These commands may remove infrastructure networks.

### Expanding Docker's Default Address Pool

For environments with many concurrent labs, expand Docker's address pool:

1. Edit `/etc/docker/daemon.json`:
   ```json
   {
     "default-address-pools": [
       {"base": "172.80.0.0/12", "size": 24},
       {"base": "192.168.0.0/16", "size": 24}
     ]
   }
   ```

   **Important**: Avoid ranges used by:
   - k3s/k8s cluster networking (typically 10.42.x.x, 10.43.x.x)
   - Your host network's subnets
   - VPNs or other infrastructure

2. Restart Docker:
   ```bash
   sudo systemctl restart docker
   ```

3. Verify the new pools:
   ```bash
   docker info | grep -A 10 "Default Address Pools"
   ```

### Example Expanded Configuration

For a development machine running k3d (uses 172.18.x.x for k3d networks):

```json
{
  "default-address-pools": [
    {"base": "172.80.0.0/12", "size": 24},
    {"base": "192.168.128.0/17", "size": 24}
  ]
}
```

This provides:
- 172.80.0.0/12: ~4096 /24 subnets (172.80-95.x.x)
- 192.168.128.0/17: ~512 /24 subnets (192.168.128-255.x)

### Monitoring

Check current network counts:
```bash
# Total networks
docker network ls --format '{{.Name}}' | wc -l

# OctoLab networks
docker network ls --format '{{.Name}}' | grep -E '^octolab_' | wc -l

# Networks by type
docker network ls --format '{{.Name}}' | grep -E '^octolab_[0-9a-f-]+_lab_net$' | wc -l
docker network ls --format '{{.Name}}' | grep -E '^octolab_[0-9a-f-]+_egress_net$' | wc -l
```

If octolab network count exceeds 200, consider:
1. Reducing `DEFAULT_LAB_TTL_MINUTES` to expire labs sooner
2. Reducing `MAX_ACTIVE_LABS_PER_USER` to limit concurrent labs
3. Expanding the Docker address pool as described above

### Automatic Cleanup

The backend performs automatic cleanup at multiple points:

1. **Preflight cleanup**: Before each lab creation, empty lab networks are cleaned up

2. **Teardown cleanup** (on lab delete/stop/failure):
   - `docker compose down --remove-orphans` stops containers and removes default networks
   - **Label-based network discovery**: Finds all networks with `com.docker.compose.project=<project>` label
   - Removes networks with 0 attached containers
   - Defense-in-depth: Only removes networks starting with `octolab_`
   - Fallback: Explicit removal for known network names (`lab_net`, `egress_net`)

3. **Provisioning failure cleanup**: When lab creation fails, `_cleanup_project` is called:
   - Runs compose down
   - Uses label-based network cleanup
   - Releases port reservation

**Why this frees subnets**: Docker allocates a /24 subnet from the address pool for each bridge network. When networks are removed, their subnets return to the pool for reuse.

The automatic cleanup will NOT:
- Remove networks with attached containers (unless they're allowlisted control-plane containers)
- Run broad `docker network prune` commands
- Touch non-lab networks

### Blocked Network Cleanup

If a network can't be removed due to attached containers:

1. Check what's attached:
   ```bash
   docker network inspect octolab_<uuid>_lab_net
   ```

2. If containers are from a failed lab, manually remove them:
   ```bash
   docker stop <container_name>
   docker rm <container_name>
   ```

3. Then remove the network:
   ```bash
   docker network rm octolab_<uuid>_lab_net
   ```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_ACTIVE_LABS_PER_USER` | 2 | Maximum concurrent labs per user |
| `DEFAULT_LAB_TTL_MINUTES` | 120 | Lab auto-expiration time |
| `OCTOLAB_CONTROL_PLANE_CONTAINERS` | `octolab-guacd` | Containers that can be force-disconnected from lab networks |
| `OCTOLAB_NET_RM_MAX_RETRIES` | 6 | Retries for network removal (handles GC race) |
| `OCTOLAB_NET_RM_BACKOFF_MS` | 200 | Backoff between network removal retries |
