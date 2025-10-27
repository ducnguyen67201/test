# zeroZero — Monorepo Engineering Spec (README)

> **Goal:** Ship a production‑ready monolith with a **Go (Gin) Clean Architecture** backend, **gRPC (Connect)** for low‑latency RPC, **tRPC + Next.js** for frontend DX, **Postgres** via **sqlc**, **Clerk** auth, and **CI/CD** via **.github/workflows**. Optimize for speed to first feature and clarity for growth.

---

## 1) Scope & Non‑Functional Requirements

- **Scope (MVP):**
  - Authenticated users can sign in via Clerk.
  - “Sync Profile” vertical slice that upserts the user in Postgres and returns the record.
  - HTTP JSON endpoint (`GET /api/me`) and gRPC method (`user.v1.UserService/GetOrCreateMe`).
- **NFRs:**
  - p95 HTTP endpoint latency < 200ms for simple CRUD on small DB (single region).
  - End‑to‑end web→API→DB for “/me” < 300ms (p50).
  - One‑command local dev (`make dev`), one‑step deploys (Vercel/Fly).
  - Zero secret sprawl: secrets in GitHub Actions + deploy targets only.
  - Clean Architecture boundaries enforced; easy to add features following the same vertical slice.

---

## 2) High‑Level Architecture

**Frontend (apps/web)**

- Next.js (App Router, TypeScript, Tailwind).
- Clerk for auth (provider + server tokens).
- **tRPC** server inside Next.js; **tRPC procedures call Connect‑Web TS gRPC client** to Go API.
- Optional REST proxy route handlers for convenience.

**Backend (apps/api)**

- Go 1.22+ with **Gin** for HTTP JSON.
- **Connect (gRPC over HTTP/2)** server for low‑latency RPC (port `:9090`).
- **Clean Architecture:** `domain` → `usecase` → `interface` (http/grpc) → `infrastructure`.
- Persistence via **sqlc** (type‑safe SQL) + `sqlx` + Postgres.
- Auth via **Clerk JWT** (JWKS verification; validate `iss`/`aud`).

**Shared Contracts (proto/)**

- Protobuf defined with **buf**; codegen for Go and TypeScript (Connect‑Web).

**CI/CD**

- GitHub Actions: proto lint/breaking + codegen checks, Go lint/tests, Web lint/build, Docker build/push, deploys to Fly (API) & Vercel (Web).

---

## 3) Repository Layout

```
your-app/
  apps/
    api/
      cmd/api/main.go
      internal/
        domain/
        usecase/
        interface/{http,grpc}
        infrastructure/{persistence,auth,logging,config,clock}
        data/
      Dockerfile
      .air.toml
    web/
      app/(marketing)/
      app/(app)/dashboard/
      shared/{ui,lib,config,hooks,styles,types}
      entities/user/
      features/profile/
      widgets/navbar/
      lib/{gen,rpc}
      env.mjs
      tsconfig.json
      .eslintrc.cjs
      .prettierrc
  proto/
  db/
  .github/workflows/
  Makefile
  .env.sample
  README.md
  .editorconfig
```

---

## 8) Environment & Secrets

\`\` (reference only)

```
# Web
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_GRPC_URL=http://localhost:9090
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=

# API
ADDR=:8080
GRPC_ADDR=:9090
DATABASE_URL=postgres://user:pass@host:5432/db?sslmode=require
CLERK_JWKS_URL=https://<clerk-domain>/.well-known/jwks.json
CLERK_JWT_AUD=yourapp-api
CLERK_JWT_ISS=https://<issuer>.clerk.accounts.dev
```

**Secret Management**

- **Local Development:**
  - Use `doppler`, `direnv`, or `1Password CLI` to inject secrets into the shell instead of storing in `.env`.
  - Example: `doppler run -- make dev` automatically provides `DATABASE_URL`, `CLERK_*`.
- **CI/CD:**
  - Use GitHub Actions Secrets → injected via `${{ secrets.VAR_NAME }}` in workflows.
  - No secrets in repo, only references.
- **Production:**
  - **Fly.io:** `fly secrets set DATABASE_URL=... CLERK_JWT_AUD=...`
  - **Vercel:** Project settings → Environment Variables.
  - Containers use mounted secret stores (Fly machine secrets, AWS/GCP Secret Manager if cloud‑native).
- **Best Practices:**
  - No secrets checked into `.env` files; only `.env.sample` for documentation.
  - Prefer short‑lived credentials (JWT, ephemeral DB tokens).
  - Rotate secrets regularly.

---

### Example — Using Doppler for Local Dev

```
# Install Doppler CLI
brew install dopplerhq/cli/doppler

# Run API with secrets
cd apps/api
doppler run -- make dev

# Run Web with secrets
cd apps/web
doppler run -- pnpm dev
```

### Example — GitHub Actions Secret Injection

```yaml
- name: Run Tests
  run: make test-api
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
    CLERK_JWKS_URL: ${{ secrets.CLERK_JWKS_URL }}
    CLERK_JWT_AUD: ${{ secrets.CLERK_JWT_AUD }}
    CLERK_JWT_ISS: ${{ secrets.CLERK_JWT_ISS }}
```

---

## Notes

- All environments should load secrets via a **secret manager** (Doppler, Vault, AWS Secrets Manager, GCP Secret Manager) rather than relying on `.env`.
- `.env.sample` documents required keys but must not contain actual values.
- Injection priority: **Runtime secret manager > CI/CD secrets > Local fallback**.

