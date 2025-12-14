# Evidence Bundle v1

This document describes the evidence bundle format, contents, and verification process.

## Overview

OctoLab generates evidence bundles that capture:
- Network traffic (pcap captures)
- Container logs
- Session recordings (tlog)
- Metadata with cryptographic checksums

Evidence is **authoritative** when sourced from trusted components (lab-gateway), and **untrusted** when from user-writable areas (OctoBox).

## Bundle Structure

```
bundle.zip
├── manifest.json           # Bundle metadata with file hashes
├── pcap/
│   └── capture.pcap*       # Network capture from lab-gateway
├── evidence/
│   ├── tlog/<lab_id>/      # Session recordings (tlog format)
│   │   └── session.jsonl
│   ├── commands.log        # Legacy terminal transcript
│   └── commands.time       # Timing data for replay
└── logs/
    ├── octobox.log         # OctoBox container logs
    ├── target-web.log      # Target container logs
    └── lab-gateway.log     # Gateway logs (network capture)
```

## Authoritative vs Untrusted Evidence

| Source | Type | Description |
|--------|------|-------------|
| `lab-gateway:/evidence/auth/` | Authoritative | Network JSON, signed manifest |
| `lab-gateway:/pcap/` | Authoritative | Network packet captures |
| Container logs via `docker logs` | Authoritative | Runtime metadata |
| `octobox:/evidence/` (evidence_user) | Untrusted | User session recordings |

**Security invariant**: OctoBox does NOT have access to `evidence_auth` volume. This prevents users from tampering with authoritative evidence.

## manifest.json

```json
{
  "lab_id": "uuid",
  "user_id": "uuid",
  "bundle_version": "1.0",
  "generated_at": "2025-12-05T10:00:00Z",
  "files": [
    {
      "path": "pcap/capture.pcap",
      "sha256": "abc123...",
      "size": 12345
    }
  ],
  "containers": [
    {
      "name": "octolab_<lab_id>-octobox-1",
      "image": "octobox-beta:dev",
      "status": "running"
    }
  ]
}
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /labs/{id}/evidence` | Legacy tar.gz archive |
| `GET /labs/{id}/evidence/bundle.zip` | Complete evidence bundle |
| `GET /labs/{id}/evidence/verified-bundle.zip` | Verified bundle with HMAC |

All endpoints require authentication and enforce tenant isolation (404 if not owner).

## Quotas & TTL

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ACTIVE_LABS_PER_USER` | 2 | Maximum concurrent labs |
| `DEFAULT_LAB_TTL_MINUTES` | 120 | Lab auto-expiration time |
| `EVIDENCE_RETENTION_HOURS` | 72 | Evidence deletion after lab end |
| `MAX_EVIDENCE_ZIP_MB` | 200 | Max bundle size (disk DoS protection) |

## Verification Commands

```bash
# Run full E2E verification (includes evidence download/validation)
make e2e-verify

# Capture system state snapshot
make snapshot

# Garbage collect expired labs and old evidence
make gc

# Run GC in dry-run mode
python3 backend/scripts/run_with_env.py \
  --env backend/.env \
  --env backend/.env.local \
  -- python3 dev/scripts/gc.py --dry-run
```

## E2E Verification Checks

The `e2e_verify.py` script validates:

1. **traffic_generation**: Generates HTTP traffic from OctoBox to target
2. **evidence_download**: Downloads bundle via API
3. **evidence_isolated**: Confirms `evidence_auth` NOT mounted in OctoBox
4. **ZIP validation**:
   - `manifest.json` present and valid
   - SHA256 hashes match
   - pcap/network.json has data
   - No secrets in logs

## Security Notes

- All subprocess calls use `shell=False` with timeouts
- Secrets are redacted from logs using `app.utils.redact`
- Evidence bundles exclude environment variables
- Container inspect data is allowlisted (no env, no sensitive host paths)
- JWT and Fernet tokens are detected and redacted

## Logs Location

Evidence bundles are stored in:
- `backend/var/evidence_bundles/<lab_id>/<timestamp>.zip`

E2E verification results are saved to:
- `backend/var/snapshots/<timestamp>/e2e_verify.json`
- `backend/var/snapshots/<timestamp>/evidence_<lab_id>.zip`
