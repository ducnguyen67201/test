# Developer Quickstart

Get OctoLab running on a single machine for development. This guide covers both Docker Compose and Firecracker runtimes.

**Time**: ~30 minutes
**Prerequisites**: Ubuntu 22.04/24.04 or WSL2

## Choose Your Runtime

| Runtime | Isolation | Requirements | Recommended For |
|---------|-----------|--------------|-----------------|
| `compose` | Container | Docker only | Quick start, simple testing |
| `firecracker` | MicroVM | KVM + setup | Full isolation testing |

Most developers start with `compose` and add `firecracker` when testing isolation.

---

## Option A: Docker Compose Runtime (Quick Start)

### 1. Clone and Install Dependencies

```bash
cd ~
git clone <repo-url> octolab_mvp
cd octolab_mvp

# Backend Python environment
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..

# Frontend (optional for API development)
cd frontend
npm install
cd ..
```

### 2. Start Services

```bash
# Bootstrap: creates .env.local, starts Guacamole, runs migrations
make dev-up

# Start the backend
make dev

# (Optional) Start frontend in another terminal
cd frontend && npm run dev
```

### 3. Verify Setup

```bash
# Health check
make dev-doctor

# API should respond at http://localhost:8000/health
curl http://localhost:8000/health
```

**You're done!** The backend uses Docker Compose to run labs.

---

## Option B: Firecracker Runtime (Full Isolation)

### 1. Prerequisites Check

```bash
# Check if KVM is available
ls -l /dev/kvm

# WSL users: Enable nested virtualization in .wslconfig:
# [wsl2]
# nestedVirtualization=true
# Then restart WSL: wsl --shutdown
```

### 2. Clone and Install

```bash
cd ~
git clone <repo-url> octolab_mvp
cd octolab_mvp

# Backend setup
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..
```

### 3. Install Firecracker Infrastructure

```bash
# Run the installer (requires root)
sudo infra/octolabctl/octolabctl.sh install

# Add yourself to octolab group (for socket access)
# This was done by install, but you need to apply it:
newgrp octolab  # Or log out and back in
```

### 4. Start Network Daemon

The network daemon creates bridges/TAPs for VM networking. It must run as root.

**On Linux with systemd:**
```bash
sudo octolabctl netd install
sudo systemctl start microvm-netd
sudo systemctl status microvm-netd
```

**On WSL (no systemd):**
```bash
sudo infra/microvm/netd/run_netd.sh --daemon
```

### 5. Verify Firecracker Setup

```bash
# Run doctor
infra/octolabctl/octolabctl.sh doctor

# Run smoke test (boots ephemeral VM)
infra/octolabctl/octolabctl.sh smoke
```

### 6. Configure Backend

```bash
# Enable Firecracker runtime
infra/octolabctl/octolabctl.sh enable-runtime firecracker

# Bootstrap other services
make dev-up

# Start backend
make dev
```

---

## Directory Structure

```
octolab_mvp/
├── backend/           # FastAPI backend
│   ├── app/          # Application code
│   ├── alembic/      # Database migrations
│   └── tests/        # Test suite
├── frontend/          # React frontend
├── infra/             # Infrastructure
│   ├── octolabctl/   # Management tool
│   ├── microvm/      # MicroVM setup scripts
│   │   └── netd/     # Network daemon
│   ├── firecracker/  # VM assets & guest agent
│   └── guacamole/    # Remote desktop gateway
├── images/            # Docker images (OctoBox)
└── docs/              # Documentation
```

## Common Tasks

### Running Tests

```bash
# All tests
make test

# Specific test
./backend/scripts/test.sh -k test_name

# With verbose output
make test-verbose
```

### Database Operations

```bash
# Run migrations
make db-migrate

# Check migration status
make db-status

# Create new migration
./dev/db_migrate.sh revision --autogenerate -m "description"
```

### Guacamole (Remote Desktop)

```bash
# Start Guacamole stack
make guac-up

# Check status
make guac-status

# Full reset (if ERROR page appears)
make guac-reset
```

### Runtime Switching

```bash
# Switch to compose (default)
octolabctl enable-runtime compose

# Switch to firecracker
octolabctl enable-runtime firecracker

# Always restart backend after switching
# Ctrl+C and `make dev` again
```

## WSL-Specific Notes

### Enable Nested Virtualization

Create or edit `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
nestedVirtualization=true
memory=8GB
processors=4
```

Then restart WSL:
```powershell
wsl --shutdown
```

### Group Membership

After `octolabctl install` adds you to the `octolab` group:

```bash
# Either open a new WSL terminal, or:
newgrp octolab

# Or fully restart WSL:
# In PowerShell: wsl --terminate Ubuntu-24.04
```

### Running netd

WSL doesn't have systemd by default. Use manual mode:

```bash
# Start in background
sudo infra/microvm/netd/run_netd.sh --daemon

# Check status
sudo infra/octolabctl/octolabctl.sh netd status

# View logs
tail -f /run/octolab/microvm-netd.log
```

## Troubleshooting

### "KVM not available"

```bash
# Check KVM
ls -l /dev/kvm

# If missing on WSL, enable nested virtualization (see above)
# If missing on Linux, ensure you're not in a VM without nested virt
```

### "Permission denied" on socket

```bash
# Check group membership
id | grep octolab

# If not in group, apply it:
newgrp octolab
# Or log out and back in
```

### "netd not responding"

```bash
# Check if running
sudo octolabctl netd status

# Check logs
sudo octolabctl netd logs -f

# Restart
sudo octolabctl netd stop
sudo octolabctl netd start
```

### Database connection issues

```bash
# Ensure PostgreSQL is running (via docker-compose or system service)
docker compose -f infra/guacamole/docker-compose.yml ps

# Check connection
psql postgresql://octolab:octolab_password@localhost:5432/octolab
```

## Next Steps

1. Read [Architecture Overview](../architecture/microvm.md)
2. Explore the [API docs](http://localhost:8000/docs) (when backend is running)
3. Check [Troubleshooting](../troubleshooting.md) for common issues
