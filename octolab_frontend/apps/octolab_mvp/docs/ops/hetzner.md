# Hetzner Ubuntu 24.04 Deployment

Deploy OctoLab on a fresh Hetzner Cloud server with Firecracker microVM isolation.

**Time**: ~1 hour
**Server**: Hetzner CPX31 or larger (4 vCPU, 8GB RAM minimum)
**OS**: Ubuntu 24.04 LTS

## Prerequisites

- Hetzner Cloud account
- SSH key added to Hetzner
- Domain name (optional, for HTTPS)

## Step 1: Create Server

1. Go to [Hetzner Cloud Console](https://console.hetzner.cloud)
2. Create new project or select existing
3. Add Server:
   - **Location**: Choose closest to your users
   - **Image**: Ubuntu 24.04
   - **Type**: CPX31 (4 vCPU, 8GB RAM) or larger
   - **Networking**: Public IPv4 + IPv6
   - **SSH Keys**: Select your key
   - **Name**: `octolab-prod` (or your preference)

4. Click Create

## Step 2: Initial Server Setup

SSH into your server:

```bash
ssh root@<server-ip>
```

### 2.1 Update System

```bash
apt update && apt upgrade -y
apt install -y curl git jq htop
```

### 2.2 Create Service User

```bash
# Create octolab user (no login shell for security)
useradd -r -m -d /opt/octolab -s /bin/bash octolab

# Create octolab group for socket access
groupadd -f octolab
usermod -aG octolab octolab
```

### 2.3 Clone Repository

```bash
cd /opt/octolab
git clone <repo-url> app
cd app
chown -R octolab:octolab /opt/octolab
```

## Step 3: Install Firecracker Infrastructure

```bash
cd /opt/octolab/app

# Run the installer
./infra/octolabctl/octolabctl.sh install

# Verify installation
./infra/octolabctl/octolabctl.sh doctor
```

Expected output:
```
[INFO] Running OctoLab microVM doctor checks...

Checking /dev/kvm... [OK] available and accessible
Checking firecracker binary... [OK] found (Firecracker v1.7.0)
Checking jailer binary... [OK] found
Checking kernel image... [OK] found (vmlinux)
Checking rootfs image... [OK] found (rootfs.ext4)
Checking state directory... [OK] exists and writable
Checking octolab group... [OK] exists
Checking microvm-netd socket... [WARN] not running
Checking vsock support... [OK] available

[OK] All critical checks passed
```

## Step 4: Install Network Daemon

```bash
# Install systemd service
./infra/octolabctl/octolabctl.sh netd install

# Start and enable
systemctl start microvm-netd
systemctl enable microvm-netd

# Verify
systemctl status microvm-netd
./infra/octolabctl/octolabctl.sh netd status
```

## Step 5: Run Smoke Test

```bash
./infra/octolabctl/octolabctl.sh smoke
```

Expected output:
```
[INFO] Running microVM smoke test...
[INFO] Smoke test ID: 20241210_143022_abc12345
[INFO] Logs: firecracker.log
[INFO] Starting microVM...
[OK] microVM started (PID 12345)
[INFO] Waiting for boot (timeout: 30s)...
[OK] Smoke test PASSED - microVM booted successfully
```

## Step 6: Install PostgreSQL

```bash
apt install -y postgresql postgresql-contrib

# Start and enable
systemctl start postgresql
systemctl enable postgresql

# Create database and user
sudo -u postgres psql << 'EOF'
CREATE USER octolab WITH PASSWORD 'CHANGE_THIS_PASSWORD';
CREATE DATABASE octolab OWNER octolab;
\q
EOF

# Test connection
psql -U octolab -h localhost -d octolab -c "SELECT 1"
```

## Step 7: Configure Backend

### 7.1 Enable Firecracker Runtime

```bash
cd /opt/octolab/app
./infra/octolabctl/octolabctl.sh enable-runtime firecracker
```

### 7.2 Create Production Environment

```bash
cat > /opt/octolab/app/backend/.env.local << 'EOF'
# Database
DATABASE_URL=postgresql+asyncpg://octolab:CHANGE_THIS_PASSWORD@localhost:5432/octolab

# Security - GENERATE NEW VALUES
SECRET_KEY=GENERATE_WITH_openssl_rand_hex_32

# Application
APP_ENV=production
LOG_LEVEL=INFO

# BEGIN OCTOLAB_MICROVM
# (octolabctl wrote this section - leave alone)
EOF
```

Generate secrets:
```bash
# Generate SECRET_KEY
openssl rand -hex 32
# Copy output and paste into .env.local
```

### 7.3 Install Python Dependencies

```bash
cd /opt/octolab/app/backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

### 7.4 Run Migrations

```bash
cd /opt/octolab/app/backend
source .venv/bin/activate
alembic upgrade head
```

## Step 8: Create Systemd Service

```bash
cat > /etc/systemd/system/octolab-backend.service << 'EOF'
[Unit]
Description=OctoLab Backend API
Documentation=https://github.com/octolab/octolab
After=network.target postgresql.service microvm-netd.service
Requires=microvm-netd.service

[Service]
Type=simple
User=octolab
Group=octolab
WorkingDirectory=/opt/octolab/app/backend
Environment=PATH=/opt/octolab/app/backend/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/octolab/app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/octolab /run/octolab /opt/octolab
PrivateTmp=true

# Restart
Restart=on-failure
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=octolab-backend

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable octolab-backend
systemctl start octolab-backend
```

Verify:
```bash
systemctl status octolab-backend
curl http://localhost:8000/health
```

## Step 9: Install Nginx (Reverse Proxy)

```bash
apt install -y nginx

cat > /etc/nginx/sites-available/octolab << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

ln -sf /etc/nginx/sites-available/octolab /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

## Step 10: (Optional) HTTPS with Let's Encrypt

```bash
apt install -y certbot python3-certbot-nginx

# Replace YOUR_DOMAIN with your actual domain
certbot --nginx -d YOUR_DOMAIN

# Auto-renewal is configured automatically
```

## Step 11: Firewall Setup

```bash
# Allow SSH, HTTP, HTTPS
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable

# Verify
ufw status
```

## Step 12: Final Verification

```bash
# Check all services
systemctl status microvm-netd
systemctl status octolab-backend
systemctl status nginx

# Run doctor
./infra/octolabctl/octolabctl.sh doctor

# Test API
curl http://localhost:8000/health
curl http://YOUR_SERVER_IP/health
```

## Monitoring & Maintenance

### View Logs

```bash
# Backend logs
journalctl -u octolab-backend -f

# Netd logs
journalctl -u microvm-netd -f

# Nginx access logs
tail -f /var/log/nginx/access.log
```

### System Health

```bash
# Doctor check
./infra/octolabctl/octolabctl.sh doctor

# Netd status
./infra/octolabctl/octolabctl.sh netd status

# Disk usage
df -h /var/lib/octolab
```

### Backup

```bash
# Database
pg_dump -U octolab octolab > /backup/octolab_$(date +%Y%m%d).sql

# Environment (contains secrets!)
cp /opt/octolab/app/backend/.env.local /backup/
```

## Troubleshooting

### Backend won't start

```bash
# Check logs
journalctl -u octolab-backend -n 100

# Common issues:
# - DATABASE_URL wrong
# - SECRET_KEY missing
# - netd not running

# Test directly
cd /opt/octolab/app/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### netd won't start

```bash
# Check logs
journalctl -u microvm-netd -n 100

# Common issues:
# - Not running as root (should be automatic via systemd)
# - /run/octolab permissions

# Manual test
sudo python3 /opt/octolab/app/infra/microvm/netd/microvm_netd.py
```

### Smoke test fails

```bash
# Run with verbose output
./infra/octolabctl/octolabctl.sh smoke -v

# Check:
# - KVM available: ls -l /dev/kvm
# - Kernel exists: ls -l /var/lib/octolab/firecracker/vmlinux
# - Rootfs exists: ls -l /var/lib/octolab/firecracker/rootfs.ext4
```

### Labs fail to start

```bash
# Check netd is responding
./infra/octolabctl/octolabctl.sh netd status

# Check state directory permissions
ls -la /var/lib/octolab/microvm/

# Check backend logs for specific error
journalctl -u octolab-backend | grep -i error
```

## Security Checklist

- [ ] Changed default PostgreSQL password
- [ ] Generated unique SECRET_KEY
- [ ] Enabled UFW firewall
- [ ] Configured HTTPS (if public-facing)
- [ ] Set up regular backups
- [ ] Reviewed systemd security settings
- [ ] Limited SSH access (key-only, disable root)

## Next Steps

1. Configure [Guacamole](../dev/quickstart.md#guacamole-remote-desktop) for remote desktop
2. Set up monitoring (Prometheus/Grafana)
3. Configure log aggregation
4. Set up automated backups
