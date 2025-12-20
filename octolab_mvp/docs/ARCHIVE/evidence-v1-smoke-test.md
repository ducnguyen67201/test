> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Evidence v1 Smoke Test

This document describes how to use the smoke test script for validating the Authoritative Evidence v1 feature.

## Overview

The smoke test validates:

1. **Security Invariant**: OctoBox cannot access authoritative evidence volume
2. **Evidence Presence**: Authoritative evidence files exist (network.json)
3. **Seal Status**: Evidence is sealed with HMAC signature
4. **Verified Bundle**: Download endpoint returns 200 with valid manifest
5. **Tamper Detection** (optional): Modified evidence returns 422

## Prerequisites

- Running backend API at `http://127.0.0.1:8000` (or specified `--api-base`)
- A lab in FINISHED status with sealed evidence
- Valid JWT token for the lab owner
- Docker available for volume inspection

## Obtaining a Token

```bash
# Login to get a token
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=your_email@example.com&password=your_password"

# Response includes access_token
# {"access_token": "eyJ...", "token_type": "bearer"}

# Export for convenience
export TOKEN="eyJ..."
```

## Basic Usage

```bash
cd backend

# Run basic smoke test
python3 -m app.scripts.smoke_evidence_v1 \
  --lab-id <lab-uuid> \
  --token "$TOKEN"
```

## Full Options

```bash
python3 -m app.scripts.smoke_evidence_v1 \
  --lab-id <lab-uuid> \
  --token "$TOKEN" \
  --api-base http://127.0.0.1:8000 \
  --compose-file ../octolab-hackvm/docker-compose.yml \
  --project octolab_<lab-uuid> \
  --auth-volume octolab_<lab-uuid>_evidence_auth \
  --out /tmp/evidence.zip \
  --timeout-seconds 30 \
  --docker-timeout 60 \
  --print-commands
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--lab-id` | Yes | - | UUID of the lab to test |
| `--token` | Yes | - | JWT bearer token |
| `--api-base` | No | `http://127.0.0.1:8000` | API base URL |
| `--compose-file` | No | Auto-detected | Path to docker-compose.yml |
| `--project` | No | `octolab_<lab-id>` | Compose project name |
| `--auth-volume` | No | From DB or deterministic | Auth evidence volume name |
| `--out` | No | `/tmp/octolab_evidence_<id>.zip` | Output path for bundle |
| `--tamper` | No | False | Enable tamper test |
| `--tamper-file` | No | `network/network.json` | File to tamper with |
| `--no-unzip` | No | False | Skip unzip verification |
| `--timeout-seconds` | No | 30 | API request timeout |
| `--docker-timeout` | No | 60 | Docker operation timeout |
| `--print-commands` | No | False | Print executed commands |

## Tamper Test

The tamper test validates that modified evidence is correctly rejected.

```bash
# WARNING: This MUTATES the evidence volume!
# Only use on disposable/test labs!

python3 -m app.scripts.smoke_evidence_v1 \
  --lab-id <lab-uuid> \
  --token "$TOKEN" \
  --tamper
```

This will:
1. Append bytes to `network/network.json` in the auth volume
2. Re-request the verified bundle
3. Verify the response is 422 (verification failed)

**WARNING**: After running the tamper test, the evidence for that lab is permanently modified. The verified bundle endpoint will always return 422.

## Example Output

```
============================================================
Evidence v1 Smoke Test
============================================================
Lab ID: 550e8400-e29b-41d4-a716-446655440000
API Base: http://127.0.0.1:8000

[1] Resolving identifiers...
    Project: octolab_550e8400-e29b-41d4-a716-446655440000
    Compose: /home/user/octolab_mvp/octolab-hackvm/docker-compose.yml
    Auth Volume: octolab_550e8400-e29b-41d4-a716-446655440000_evidence_auth
    Output: /tmp/octolab_evidence_550e8400-e29b-41d4-a716-446655440000.zip

[2] API preflight...
[PASS] API lab fetch
    Status: finished
    Seal Status: sealed

[3] Checking OctoBox auth isolation...
[PASS] OctoBox cannot access auth

[4] Checking auth evidence exists...
[PASS] Auth network.json exists

[5] Checking seal status...
[PASS] Seal status SEALED

[6] Downloading verified bundle...
[PASS] Verified bundle 200 + contains manifest
       Saved to /tmp/octolab_evidence_550e8400-e29b-41d4-a716-446655440000.zip
       Contains 5 files

============================================================
SUMMARY
============================================================
  [PASS] API lab fetch
  [PASS] OctoBox cannot access auth
  [PASS] Auth network.json exists
  [PASS] Seal status SEALED
  [PASS] Verified bundle 200 + contains manifest

Passed: 5/5
All checks passed!
```

## Exit Codes

- `0`: All checks passed
- `1`: One or more checks failed

## Troubleshooting

### "401 Unauthorized"
- Token is invalid or expired
- Re-authenticate and get a new token

### "404 Not Found"
- Lab doesn't exist or you don't own it
- Verify lab ID and that you're using the correct user's token

### "409 Conflict - evidence not sealed yet"
- Lab is still running or sealing hasn't completed
- End the lab and wait for teardown to complete

### "Could not exec into octobox"
- Lab containers are not running
- The test requires the lab to be running for the OctoBox isolation check
- For finished labs, this check may fail but other checks can still pass

### "Could not inspect auth volume"
- Docker may not have access to the volume
- Ensure you're running on the same Docker host as the lab

## Security Notes

- **Never share tokens** in logs or output
- The `--print-commands` flag redacts sensitive values
- Tamper tests should only be run on disposable labs
- The script uses `shell=False` for all subprocess calls
