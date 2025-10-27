# ZeroZero - Production-Ready Monorepo

A complete production-ready monorepo system featuring Go backend with Clean Architecture, Next.js frontend, gRPC/Connect communication, and Clerk authentication.

## Architecture Overview

```
zerozero/
├── apps/
│   ├── api/          # Go backend with Clean Architecture
│   └── web/          # Next.js frontend
├── proto/            # Protocol Buffer definitions
├── db/               # Database migrations and queries
├── scripts/          # Setup and utility scripts
└── .github/          # CI/CD workflows
```

### Tech Stack

**Backend (Go)**
- Gin HTTP framework
- Connect gRPC server
- Clean Architecture (Domain → UseCase → Interface → Infrastructure)
- PostgreSQL with sqlc for type-safe queries
- Clerk JWT authentication
- Redis for caching

**Frontend (Next.js)**
- App Router with Server Components
- tRPC for type-safe API calls
- Connect-Web gRPC client
- Clerk authentication
- Tailwind CSS
- TypeScript with strict mode

**Infrastructure**
- Docker & Docker Compose
- GitHub Actions CI/CD
- Protocol Buffers with buf
- Database migrations

## Quick Start

### Prerequisites

- Node.js 20+
- Go 1.21+
- Docker & Docker Compose
- Make

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/zerozero.git
cd zerozero
```

2. Copy environment variables:
```bash
cp .env.example .env.local
```

3. Update `.env.local` with your Clerk keys:
```env
CLERK_SECRET_KEY=sk_test_your_key
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_key
```

4. Run setup script:

**Linux/Mac:**
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

**Windows (PowerShell):**
```powershell
.\scripts\setup.ps1
```

5. Start development environment:
```bash
make dev
```

The application will be available at:
- Frontend: http://localhost:3000
- API: http://localhost:8080
- Health check: http://localhost:8080/health

## Development

### Available Commands

```bash
# Development
make dev              # Start all services
make build            # Build all applications
make test             # Run all tests
make clean            # Clean build artifacts

# Database
make migrate-up       # Run migrations
make migrate-down     # Rollback migrations
make sqlc-generate    # Generate sqlc code

# Protocol Buffers
make proto-generate   # Generate protobuf code
make proto-lint       # Lint proto files

# Docker
make docker-up        # Start Docker services
make docker-down      # Stop Docker services
make docker-clean     # Clean Docker volumes
```

### Project Structure

```
apps/api/
├── cmd/server/       # Application entry point
├── internal/
│   ├── domain/       # Business entities and interfaces
│   ├── usecase/      # Business logic
│   ├── interface/    # HTTP and gRPC handlers
│   └── infrastructure/ # External services (DB, auth, cache)
└── pkg/              # Shared packages

apps/web/
├── app/              # Next.js App Router
├── components/       # React components
├── lib/              # Utilities and clients
│   ├── trpc/        # tRPC setup
│   └── grpc/        # gRPC client
├── hooks/           # Custom React hooks
└── types/           # TypeScript types
```

## API Endpoints

### REST API

- `GET /health` - Health check
- `GET /api/me` - Get/create authenticated user
- `PATCH /api/me` - Update user profile

### gRPC Services

- `UserService.GetOrCreateMe` - Get or create user
- `UserService.UpdateProfile` - Update user profile

### tRPC Endpoints

- `user.me` - Get current user
- `user.syncProfile` - Sync profile with backend
- `user.updateProfile` - Update profile

## Authentication

The system uses Clerk for authentication:

1. User signs in via Clerk
2. Clerk provides a JWT token
3. Backend validates JWT and extracts user info
4. User profile is synced to database on first access

## Database Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    clerk_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Testing

```bash
# Run all tests
make test

# API tests
cd apps/api && go test ./...

# Frontend tests
cd apps/web && npm test

# E2E tests (when available)
npm run test:e2e
```

## Deployment

### Docker

Build and run with Docker:

```bash
# Build images
docker build -f apps/api/Dockerfile -t zerozero-api .
docker build -f apps/web/Dockerfile -t zerozero-web .

# Run with docker-compose
docker-compose -f docker-compose.prod.yml up
```

### CI/CD

The project includes GitHub Actions workflows:

- **CI Pipeline**: Runs on every push
  - Lints protocol buffers
  - Runs API tests
  - Runs frontend tests
  - Builds Docker images
  - Security scanning

- **Deploy Pipeline**: Runs on main branch
  - Builds and pushes images
  - Deploys to staging
  - Runs smoke tests
  - Deploys to production

## Environment Variables

### API

- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `CLERK_SECRET_KEY` - Clerk secret key
- `API_PORT` - Server port (default: 8080)
- `API_CORS_ORIGINS` - Allowed CORS origins

### Frontend

- `NEXT_PUBLIC_API_URL` - Backend API URL
- `NEXT_PUBLIC_GRPC_URL` - gRPC endpoint URL
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Clerk public key
- `CLERK_SECRET_KEY` - Clerk secret key

## Production Considerations

1. **Security**
   - All endpoints require authentication (except health checks)
   - JWT validation on every request
   - Input sanitization and validation
   - Rate limiting ready to implement

2. **Monitoring**
   - Structured logging throughout
   - Health check endpoints
   - Ready for integration with APM tools

3. **Scalability**
   - Stateless services
   - Horizontal scaling ready
   - Database connection pooling
   - Redis caching layer

4. **Error Handling**
   - Comprehensive error types
   - Proper error propagation
   - User-friendly error messages

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details