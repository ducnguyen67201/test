# OctoLab

**CVE rehearsal platform for penetration testers and red teams.**

OctoLab spins up isolated lab environments (attacker-box + vulnerable targets) for exploit rehearsal and generates evidence reports. The goal is safe exploit practice with auditable evidence, not generic training.

## Quick Start

```bash
# 1. Clone and setup backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd ..

# 2. Bootstrap environment
make dev-up    # Creates .env.local, starts Guacamole, runs migrations

# 3. Start backend
make dev       # FastAPI server at localhost:8000

# 4. Verify
curl http://localhost:8000/health
```

For Firecracker (microVM) runtime:
```bash
sudo infra/octolabctl/octolabctl.sh install
sudo infra/octolabctl/octolabctl.sh netd start
infra/octolabctl/octolabctl.sh enable-runtime firecracker
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    nginx (port 80)                           │
│  /api/* → Backend    /guacamole/* → Guacamole               │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌───────────┐   ┌───────────────┐
    │ Backend  │   │ Guacamole │   │ PostgreSQL    │
    │ FastAPI  │   │ (VNC GW)  │   │               │
    └────┬─────┘   └───────────┘   └───────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              Lab Runtime (Firecracker or Compose)            │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │   OctoBox      │  │ Vulnerable      │  │ Lab Gateway  │  │
│  │ (Attacker VM)  │  │ Target          │  │ (Evidence)   │  │
│  └────────────────┘  └─────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Documentation

| Document | Description |
|----------|-------------|
| [docs/README.md](docs/README.md) | Full documentation index |
| [docs/dev/quickstart.md](docs/dev/quickstart.md) | Developer setup guide |
| [docs/ops/hetzner.md](docs/ops/hetzner.md) | Production deployment |
| [docs/architecture/microvm.md](docs/architecture/microvm.md) | MicroVM architecture |
| [CLAUDE.md](CLAUDE.md) | AI assistant context |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.x, PostgreSQL
- **Frontend**: React + TypeScript (Vite)
- **Remote Desktop**: Apache Guacamole (VNC gateway)
- **Lab Isolation**: Firecracker microVMs (production) or Docker Compose (dev)
- **Evidence**: Command logging, network captures, HMAC-sealed bundles

## Project Structure

```
octolab_mvp/
├── backend/           # FastAPI backend
│   ├── app/          # Application code
│   │   ├── api/      # HTTP endpoints
│   │   ├── models/   # SQLAlchemy models
│   │   ├── services/ # Business logic
│   │   └── runtime/  # Lab runtime implementations
│   └── tests/        # Test suite
├── frontend/          # React frontend
├── infra/             # Infrastructure
│   ├── octolabctl/   # CLI management tool
│   ├── guacamole/    # Remote desktop gateway
│   └── firecracker/  # MicroVM assets
├── images/            # Docker images (OctoBox)
└── docs/              # Documentation
```

## Commands

```bash
# Development
make dev-up          # Bootstrap environment
make dev             # Start FastAPI server
make test            # Run tests

# Guacamole (Remote Desktop)
make guac-up         # Start Guacamole stack
make guac-status     # Check status

# Firecracker (Production Runtime)
infra/octolabctl/octolabctl.sh doctor    # Check prerequisites
infra/octolabctl/octolabctl.sh smoke     # Test VM boot
```

## Configuration

Copy example files and configure:
```bash
cp .env.prod.example .env.prod
cp backend/.env.local.example backend/.env.local
```

Key environment variables:
- `DATABASE_URL` - PostgreSQL connection
- `SECRET_KEY` - JWT signing key
- `GUAC_ENC_KEY` - Guacamole password encryption
- `OCTOLAB_RUNTIME` - Runtime: `compose` or `firecracker`

See [docs/README.md](docs/README.md) for full configuration reference.

## License

Proprietary - CyberOctopusVN
