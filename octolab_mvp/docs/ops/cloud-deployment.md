# OctoLab Cloud Deployment Guide

This guide covers deploying OctoLab to a Hetzner cloud server (or similar Ubuntu-based VPS) with Firecracker microVM runtime.

## Architecture Overview

```
                    ┌──────────────────────────────────────────────────────┐
                    │                   Hetzner CPX22                       │
                    │                  (Ubuntu 24.04)                       │
                    │                                                       │
    Internet        │  ┌──────────────────────────────────────────────┐    │
        │           │  │           Docker Compose Stack                │    │
        │           │  │                                               │    │
        ▼           │  │  ┌─────────┐  ┌─────────┐  ┌──────────────┐  │    │
  ┌──────────┐      │  │  │ nginx   │  │ backend │  │  postgres    │  │    │
  │Cloudflare│──────┼──┼──│:80      │──│:8000    │──│  :5432       │  │    │
  │  Proxy   │      │  │  │(frontend│  │(FastAPI)│  │  (internal)  │  │    │
  └──────────┘      │  │  └─────────┘  └────┬────┘  └──────────────┘  │    │
                    │  └───────────────────┼──────────────────────────┘    │
                    │                      │                                │
                    │           ┌──────────┴──────────┐                     │
                    │           │    Host Services    │                     │
                    │           │                     │                     │
                    │           │  ┌───────────────┐  │                     │
                    │           │  │  microvm-netd │◄─┼── /run/octolab/     │
                    │           │  │  (root)       │  │   microvm-netd.sock │
                    │           │  └───────┬───────┘  │                     │
                    │           │          │          │                     │
                    │           │  ┌───────▼───────┐  │                     │
                    │           │  │  Firecracker  │◄─┼── /var/lib/octolab/ │
                    │           │  │  microVMs     │  │   microvm/          │
                    │           │  └───────────────┘  │                     │
                    │           └─────────────────────┘                     │
                    └──────────────────────────────────────────────────────┘
```

## Prerequisites

### Server Requirements
- Hetzner CPX22 or equivalent (4 vCPU, 8GB RAM recommended)
- Ubuntu 24.04 LTS
- KVM support enabled (for Firecracker)
- Domain configured via Cloudflare (e.g., dev.cyberoctopusvn.com)

### Software Requirements
- Docker CE 24.0+
- Docker Compose v2.20+
- Node.js 20+ (for frontend build)
- Python 3.11+ (for netd)

## Server Setup

### 1. Initial Server Configuration

```bash
# SSH into your server
ssh trung@<server-ip>

# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y \
    docker.io \
    docker-compose-plugin \
    nodejs npm \
    python3 python3-pip \
    curl git

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify KVM support (required for Firecracker)
ls -la /dev/kvm
# Should show: crw-rw---- 1 root kvm ...

# Add user to kvm group
sudo usermod -aG kvm $USER
```

### 2. Create OctoLab Directories

```bash
# Create required directories
sudo mkdir -p /opt/octolab
sudo mkdir -p /var/lib/octolab/microvm
sudo mkdir -p /var/lib/octolab/firecracker
sudo mkdir -p /run/octolab
sudo mkdir -p /var/log/octolab

# Create octolab group for socket access
sudo groupadd -f octolab
sudo usermod -aG octolab $USER

# Set permissions
sudo chown -R $USER:octolab /opt/octolab
sudo chown -R $USER:octolab /var/lib/octolab
sudo chmod 750 /run/octolab
sudo chmod 750 /var/lib/octolab/microvm
```

### 3. Install Firecracker

```bash
# Download Firecracker release
ARCH=$(uname -m)
FC_VERSION="1.5.1"

curl -L -o firecracker-${FC_VERSION}.tgz \
    https://github.com/firecracker-microvm/firecracker/releases/download/v${FC_VERSION}/firecracker-v${FC_VERSION}-${ARCH}.tgz

tar -xzf firecracker-${FC_VERSION}.tgz

# Install binaries
sudo mv release-v${FC_VERSION}-${ARCH}/firecracker-v${FC_VERSION}-${ARCH} /usr/local/bin/firecracker
sudo mv release-v${FC_VERSION}-${ARCH}/jailer-v${FC_VERSION}-${ARCH} /usr/local/bin/jailer
sudo chmod +x /usr/local/bin/firecracker /usr/local/bin/jailer

# Verify installation
firecracker --version
jailer --version

# Clean up
rm -rf release-v${FC_VERSION}-${ARCH} firecracker-${FC_VERSION}.tgz
```

### 4. Prepare Firecracker Assets

```bash
# Create assets directory
mkdir -p /var/lib/octolab/firecracker

# Download kernel (example - use your preferred kernel)
# See: https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md
curl -L -o /var/lib/octolab/firecracker/vmlinux \
    https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/x86_64/vmlinux-5.10.186

# Build or copy your rootfs.ext4
# This should be your OctoBox image converted to ext4
# See: infra/firecracker/build-rootfs.sh
```

## Deployment

### 1. Clone Repository

```bash
cd /opt/octolab
git clone https://github.com/your-org/octolab_mvp.git .
# Or copy from your local machine
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.prod.example .env.prod
chmod 600 .env.prod

# Generate secrets
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env.prod
echo "EVIDENCE_HMAC_SECRET=$(openssl rand -hex 32)" >> .env.prod
echo "DB_PASSWORD=$(openssl rand -base64 24)" >> .env.prod

# Edit .env.prod with your settings
vim .env.prod
```

Key settings to configure:
- `DB_PASSWORD` - PostgreSQL password
- `SECRET_KEY` - JWT signing secret
- `EVIDENCE_HMAC_SECRET` - Evidence integrity secret
- `VNC_BASE_URL` - Your public VNC URL
- `HACKVM_PUBLIC_HOST` - Your domain
- `OCTOLAB_ADMIN_EMAILS` - Admin email addresses

### 3. Install netd Service

```bash
# Copy systemd service file
sudo cp infra/microvm/netd/microvm-netd.prod.service /etc/systemd/system/microvm-netd.service

# Edit path if needed
sudo vim /etc/systemd/system/microvm-netd.service
# Update ExecStart path to: /opt/octolab/infra/microvm/netd/microvm_netd.py

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable microvm-netd
sudo systemctl start microvm-netd

# Verify it's running
sudo systemctl status microvm-netd
ls -la /run/octolab/microvm-netd.sock
```

### 4. Deploy OctoLab

```bash
cd /opt/octolab

# Run deployment script
./deploy.sh
```

This will:
1. Build the React frontend
2. Start PostgreSQL, backend, and nginx containers
3. Run database migrations
4. Verify health checks

### 5. Verify Deployment

```bash
# Check service status
./deploy.sh --status

# Check health endpoints
curl http://localhost:8000/health
curl http://localhost/

# View logs
./deploy.sh --logs
```

## Post-Deployment

### Configure Cloudflare

1. Add DNS A record for `dev.cyberoctopusvn.com` pointing to server IP
2. Enable Cloudflare proxy (orange cloud)
3. Set SSL/TLS to "Full" mode
4. Add page rules if needed

### Create Admin User

```bash
# Connect to running backend container
docker compose -f docker-compose.prod.yml exec backend bash

# Create admin user via API or database
# Option 1: Enable self-signup temporarily and register
# Option 2: Direct database insert
```

### Set Up Log Rotation

```bash
# Create logrotate config
sudo tee /etc/logrotate.d/octolab << EOF
/var/log/octolab/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root octolab
}
EOF
```

### Set Up Backups

```bash
# Database backup script
cat > /opt/octolab/backup-db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/var/lib/octolab/backups
mkdir -p $BACKUP_DIR
docker compose -f /opt/octolab/docker-compose.prod.yml exec -T postgres \
    pg_dump -U octolab octolab | gzip > $BACKUP_DIR/octolab-$(date +%Y%m%d-%H%M%S).sql.gz
# Keep last 7 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
EOF
chmod +x /opt/octolab/backup-db.sh

# Add to crontab
echo "0 2 * * * /opt/octolab/backup-db.sh" | sudo tee -a /etc/crontab
```

## Maintenance

### Updating OctoLab

```bash
cd /opt/octolab

# Pull latest code
git pull

# Rebuild and redeploy
./deploy.sh
```

### Viewing Logs

```bash
# All services
./deploy.sh --logs

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend

# netd service
sudo journalctl -u microvm-netd -f
```

### Stopping Services

```bash
./deploy.sh --down
sudo systemctl stop microvm-netd
```

### Database Access

```bash
# Connect to PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres psql -U octolab -d octolab

# Run migrations manually
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Troubleshooting

### netd Socket Not Found

```bash
# Check if netd is running
sudo systemctl status microvm-netd

# Check socket permissions
ls -la /run/octolab/

# Restart netd
sudo systemctl restart microvm-netd
```

### Backend Can't Connect to Database

```bash
# Check database container
docker compose -f docker-compose.prod.yml ps postgres

# Check database logs
docker compose -f docker-compose.prod.yml logs postgres

# Verify DATABASE_URL in .env.prod
```

### Firecracker Permission Denied

```bash
# Check KVM access
ls -la /dev/kvm

# Add user to kvm group
sudo usermod -aG kvm $USER
newgrp kvm

# Verify firecracker can run
firecracker --version
```

### Frontend 502 Bad Gateway

```bash
# Check backend is running
docker compose -f docker-compose.prod.yml ps backend
curl http://localhost:8000/health

# Check nginx logs
docker compose -f docker-compose.prod.yml logs frontend
```

## Security Considerations

1. **Firewall**: Configure UFW to only allow ports 80, 443, and SSH
2. **SSH**: Use key-based authentication, disable password auth
3. **Secrets**: Never commit `.env.prod` to version control
4. **Updates**: Regularly update system packages and Docker images
5. **Monitoring**: Set up monitoring for service health and resource usage
