# noVNC Readiness Gating

## Problem

Labs were being marked as "spawned/READY" before noVNC was actually reachable, leading to users receiving unreachable connection URLs.

## Solution

Server-side readiness gating with the following features:

1. **Readiness Probe**: TCP + HTTP checks before marking lab READY
2. **Failure Handling**: Automatic FAILED status + diagnostics collection on timeout
3. **Best-Effort Cleanup**: Teardown on failure to prevent resource leaks
4. **Admin Diagnostics**: Script to inspect lab runtime status

## Architecture

### Readiness Flow

```
runtime.create_lab()
   ↓
Port allocated
   ↓
Readiness probe (TCP + HTTP)
   ↓
   ├─→ Success: Mark READY, set connection_url
   └─→ Failure: Mark FAILED, collect diagnostics, teardown
```

### Components

**1. Readiness Probe (`app/services/novnc_probe.py`)**
- TCP connection check (fast failure if port not listening)
- HTTP GET to multiple paths (`vnc.html`, `vnc_lite.html`, `/`)
- Accepts 2xx/3xx status codes
- Short per-attempt timeouts to prevent hanging
- Only probes server-controlled host:port combinations (security)

**2. Diagnostics Collector (`app/utils/diagnostics.py`)**
- Collects `docker compose ps` output
- Collects last N lines of compose logs
- Truncates output to prevent log bombs
- Redacts sensitive data (owner IDs, secrets)
- Admin-only (not exposed to tenants)

**3. Lab Service Integration (`app/services/lab_service.py`)**
- Gates READY transition with probe (compose runtime only)
- Collects diagnostics on failure
- Marks FAILED + sets finished_at on probe timeout
- Best-effort teardown to prevent resource leaks
- Releases port reservations

**4. Admin Diagnostic Script (`app/scripts/diagnose_lab_runtime.py`)**
- Inspect single lab runtime status
- Run quick readiness probe test
- View compose ps/logs
- Redacted output (owner ID hidden)

## Configuration

New settings in `app/config.py`:

```python
# Enable/disable gating (default: enabled)
NOVNC_READY_GATING_ENABLED=true

# Probe timeout (default: 120 seconds)
NOVNC_READY_TIMEOUT_SECONDS=120

# Poll interval between attempts (default: 1.0 seconds)
NOVNC_READY_POLL_INTERVAL_SECONDS=1.0

# HTTP paths to probe (default: vnc.html, vnc_lite.html, /)
NOVNC_READY_PATHS=["vnc.html", "vnc_lite.html", ""]
```

## Usage

### Normal Operation

No changes needed. Readiness gating is enabled by default.

Labs will transition to READY only after noVNC is confirmed reachable.

### Disabling Gating (Rollback)

If issues arise, disable gating to restore old behavior:

```bash
# In .env
NOVNC_READY_GATING_ENABLED=false
```

Restart backend service to apply.

### Admin Diagnostics

Inspect a failing lab:

```bash
cd backend
python -m app.scripts.diagnose_lab_runtime --lab-id <uuid>
```

Output includes:
- Lab status and metadata
- Expected noVNC URL
- Quick readiness probe test
- Docker compose ps output
- Recent compose logs (last 50 lines)

Example:

```
================================================================================
LAB DIAGNOSTICS
================================================================================
Lab ID:        a1b2c3d4-e5f6-7890-abcd-ef1234567890
Owner:         ****abc123 (redacted)
Status:        failed
Recipe ID:     ...
Connection URL: None
...

READINESS PROBE TEST
--------------------------------------------------------------------------------
✗ Readiness probe FAILED: noVNC endpoint 127.0.0.1:38044 not ready after 10.0s

DOCKER COMPOSE DIAGNOSTICS
--------------------------------------------------------------------------------
Project Name:  octolab_a1b2c3d4-e5f6-7890-abcd-ef1234567890

--- compose ps ---
NAME                STATE     ...
novnc-container     exited(1)
octobox-container   running

--- compose logs (last 50 lines) ---
novnc-container | Error: Connection refused
...
```

## Security

✅ **Server-controlled URLs**: Probe only fetches from server-controlled host:port
✅ **No secrets in logs**: Owner IDs redacted, no DATABASE_URL printed
✅ **Truncated output**: Logs capped to prevent log bombs
✅ **shell=False**: All subprocess calls use argument lists
✅ **Admin-only diagnostics**: Not exposed to tenants via HTTP

## Failure Scenarios

### Scenario 1: OctoBox Container Crashes on Startup

**Before**: Lab marked READY with unreachable URL

**After**:
1. Readiness probe times out (no HTTP response)
2. Diagnostics collected (shows exited container)
3. Lab marked FAILED with finished_at set
4. Best-effort teardown runs
5. Port released for reuse
6. Admin can inspect with diagnose script

### Scenario 2: noVNC Port Not Listening

**Before**: Connection URL points to closed port

**After**:
1. TCP probe fails (connection refused)
2. Probe retries until timeout
3. Lab marked FAILED
4. Diagnostics show port status
5. Cleanup and port release

### Scenario 3: noVNC Slow to Start

**Before**: Race condition - might work or fail depending on timing

**After**:
1. Probe polls every 1 second
2. Waits up to 120 seconds (configurable)
3. Marks READY once HTTP 200/301/302 received
4. No false failures from slow startup

## Testing

### Unit Tests

```bash
./backend/scripts/test.sh tests/test_novnc_readiness_gate.py -v
```

Tests cover:
- Success path (probe succeeds → READY)
- Failure path (probe fails → FAILED + diagnostics)
- Gating disabled (immediate READY)
- Exception messages
- TCP probe integration

### Manual Testing

1. **Start a lab** with gating enabled:
   ```bash
   # Backend logs should show:
   # "noVNC readiness probe succeeded for lab <id> (port 38044, elapsed 2.3s)"
   # Lab status: READY
   ```

2. **Simulate OctoBox crash**:
   ```bash
   # Stop containers manually
   docker stop octolab_<lab-id>_novnc_1

   # Start lab creation
   # Backend logs should show:
   # "noVNC readiness probe failed for lab <id>"
   # "Diagnostics for failed lab <id>:"
   # Lab status: FAILED
   ```

3. **Run diagnostic script**:
   ```bash
   python -m app.scripts.diagnose_lab_runtime --lab-id <uuid>
   ```

## Monitoring

### Log Messages

**Success**:
```
INFO: noVNC readiness probe succeeded for lab <id> (port 38044, elapsed 2.3s)
```

**Failure**:
```
ERROR: noVNC readiness probe failed for lab <id> (owner=****abc123, port 38044, elapsed 120.1s): NovncNotReady
WARNING: Diagnostics for failed lab <id>:
...
```

**Best-Effort Teardown**:
```
INFO: Best-effort teardown completed for failed lab <id>
```

or

```
WARNING: Best-effort teardown failed for lab <id>: TimeoutError
```

### Metrics to Track

- Probe success rate
- Average probe duration
- Failure reasons (TCP vs HTTP)
- Labs marked FAILED by readiness gating

## Troubleshooting

### All Labs Failing Readiness Probe

**Check**:
1. Is noVNC actually starting? (`docker compose ps`)
2. Are ports being allocated correctly? (check `novnc_host_port` in DB)
3. Is bind host correct? (should be `127.0.0.1`)
4. Firewall blocking localhost connections?

**Quick Fix**:
```bash
# Disable gating temporarily
NOVNC_READY_GATING_ENABLED=false

# Investigate root cause
# Re-enable once fixed
```

### Probe Timing Out on Slow Systems

**Increase timeout**:
```bash
NOVNC_READY_TIMEOUT_SECONDS=300  # 5 minutes
```

### False Failures Due to Network Issues

**Check probe paths**:
```bash
curl -v http://127.0.0.1:<port>/vnc.html
curl -v http://127.0.0.1:<port>/
```

If one path works but not others, adjust:
```bash
NOVNC_READY_PATHS='[""]'  # Only probe root "/"
```

## Future Enhancements

1. **Exponential backoff** for probe retries
2. **HTTP library** instead of curl subprocess
3. **Kubernetes support** for readiness gating
4. **Metrics collection** (Prometheus integration)
5. **Retry logic** for transient failures before marking FAILED
6. **Websocket handshake test** (more thorough than HTTP GET)

## References

- Implementation: `backend/app/services/novnc_probe.py`
- Integration: `backend/app/services/lab_service.py` (provision_lab function)
- Diagnostics: `backend/app/utils/diagnostics.py`
- Admin script: `backend/app/scripts/diagnose_lab_runtime.py`
- Tests: `backend/tests/test_novnc_readiness_gate.py`
