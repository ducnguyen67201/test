# Apache Guacamole Stack for OctoLab

This directory contains the Docker Compose stack for running Apache Guacamole in the OctoLab development environment.

## Overview

Apache Guacamole provides a clientless remote desktop gateway that supports VNC, RDP, and SSH protocols. In OctoLab, Guacamole replaces noVNC for accessing lab environments.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OctoLab Backend                                                │
│  - Creates Guac users/connections via API                       │
│  - Connects guacd to lab networks                               │
│  - Generates auth tokens for /labs/{id}/connect                 │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Guacamole Stack (this compose file)                            │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ octolab-guacamole│  │ octolab-guacd│  │ octolab-guac-db  │  │
│  │ (Web UI + API)   │  │ (Protocol    │  │ (PostgreSQL)     │  │
│  │ 127.0.0.1:8081   │  │  Proxy)      │  │ No host port     │  │
│  └──────────────────┘  └──────────────┘  └──────────────────┘  │
│           │                   │                                 │
│           └───────────────────┴─── guac-internal network        │
└─────────────────────────────────────────────────────────────────┘
                              │
                    docker network connect
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Lab Network (octolab_<lab_id>_lab_net)                         │
│  ┌──────────────────┐                                           │
│  │ octobox          │ VNC on port 5901                          │
│  │ (Lab Environment)│◄─────── guacd connects here               │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Start the Guacamole Stack

```bash
cd infra/guacamole
docker compose up -d
```

### 2. Verify Services

```bash
# Check all containers are running
docker compose ps

# View logs
docker compose logs -f

# Test web UI is accessible
curl -I http://127.0.0.1:8081/guacamole/
```

### 3. Access Web UI

Open http://127.0.0.1:8081/guacamole/ in your browser.

Default credentials:
- Username: `guacadmin`
- Password: `guacadmin`

**SECURITY: Change the admin password after first login!**

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GUAC_DB_PASSWORD` | `guacamole_dev_password` | PostgreSQL password |

### Backend Integration

Add these to your `backend/.env`:

```bash
# Enable Guacamole integration
GUAC_ENABLED=true

# Guacamole API settings
GUAC_BASE_URL=http://127.0.0.1:8081/guacamole
GUAC_ADMIN_USER=guacadmin
GUAC_ADMIN_PASSWORD=guacadmin

# Encryption key for per-lab passwords (generate with command below)
GUAC_ENC_KEY=<your-32-byte-base64-key>
```

Generate an encryption key:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Security Notes

1. **Localhost Binding**: The Guacamole web UI only binds to `127.0.0.1:8081`. It is NOT accessible from external networks.

2. **No Exposed Ports**: guacd and PostgreSQL have no published ports and are only accessible within the Docker network.

3. **guacd Network Isolation**: guacd is connected to lab networks dynamically by the backend. This allows it to reach VNC servers without exposing them.

4. **Per-Lab Users**: Each lab gets its own Guacamole user with a randomly generated password. Users can only access their own connections.

5. **Password Encryption**: Per-lab passwords are encrypted with Fernet (AES-128) before storage in the database.

## Troubleshooting

### Guacamole Not Starting

Check the logs:
```bash
docker compose logs octolab-guacamole
```

Common issues:
- Database not ready: Wait for `octolab-guac-db` to be healthy
- Init script error: Check `docker compose logs octolab-guac-db`

### Cannot Connect to Lab

1. Verify guacd is connected to the lab network:
   ```bash
   docker network inspect octolab_<lab_id>_lab_net
   ```

2. Check guacd logs:
   ```bash
   docker compose logs octolab-guacd
   ```

3. Verify OctoBox VNC is running:
   ```bash
   docker exec octobox netstat -tlnp | grep 5901
   ```

### Reset Everything

```bash
docker compose down -v
docker compose up -d
```

## Upgrading

To upgrade Guacamole:

1. Update the image version in `docker-compose.yml`
2. Check for schema changes in the release notes
3. Run `docker compose pull && docker compose up -d`

## References

- [Apache Guacamole Manual](https://guacamole.apache.org/doc/gug/)
- [Guacamole API Documentation](https://guacamole.apache.org/doc/guacamole-common-js/)
- [guacamole-client GitHub](https://github.com/apache/guacamole-client)
