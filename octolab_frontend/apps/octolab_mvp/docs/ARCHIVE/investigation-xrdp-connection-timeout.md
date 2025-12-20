> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Connection Timeout in OctoBox Beta

**Date:** 2025-11-22  
**Component:** OctoBox Beta (G2 Slice)  
**Issue:** Guacamole RDP connections to OctoBox Beta timeout with "server taking too long to respond"  
**Status:** Root cause identified, fixes required

---

## Executive Summary

OctoBox Beta pod is running and XRDP is listening on port 3389, but RDP connections from Guacamole timeout during session establishment. The root cause is **DBus failing to start** due to missing system configuration file, which prevents XFCE desktop from launching. XRDP accepts connections but cannot complete the session setup because the desktop environment cannot start.

---

## Problem Statement

### Symptom
- Guacamole shows error: "The connection has been closed because the server is taking too long to respond"
- Connection attempts from Guacamole to `octobox-beta-rdp.octolab-labs.svc.cluster.local:3389` timeout
- Multiple XRDP child processes spawn (indicating connection attempts) but sessions fail

### Environment
- **Kubernetes:** Single-node k3s cluster
- **Namespace:** `octolab-labs`
- **Image:** `octobox-beta:dev` (Debian 12-slim base)
- **XRDP Version:** 0.9.x (from Debian 12 repos)
- **Desktop:** XFCE 4.18+

---

## Investigation Findings

### 1. Network Connectivity: ✅ WORKING

**Evidence:**
```bash
# XRDP is listening on port 3389
$ kubectl exec -n octolab-labs $POD -- ss -tlnp | grep 3389
LISTEN 0      2                  *:3389            *:*    users:(("xrdp",pid=14,fd=10))

# Service endpoint is correct
$ kubectl get endpoints -n octolab-labs octobox-beta-rdp
NAME               ENDPOINTS          AGE
octobox-beta-rdp   10.42.0.244:3389   10m

# Connectivity from guacd pod works
$ kubectl exec -n octolab-system $GUACD_POD -- nc -zv octobox-beta-rdp.octolab-labs.svc.cluster.local 3389
Connection to octobox-beta-rdp.octolab-labs.svc.cluster.local (10.43.140.80) 3389 port [tcp/ms-wbt-server] succeeded!

# Local connectivity works
$ kubectl exec -n octolab-labs $POD -- nc -zv localhost 3389
Connection to localhost (::1) 3389 port [tcp/*] succeeded!
```

**Conclusion:** Network layer is functioning correctly. XRDP daemon is running and accepting connections.

---

### 2. XRDP Processes: ⚠️ MULTIPLE CHILD PROCESSES

**Evidence:**
```bash
$ kubectl exec -n octolab-labs $POD -- ps aux | grep xrdp
root        13  0.0  0.0  11668  3840 ?        S    08:15   0:00 /usr/sbin/xrdp-sesman --nodaemon
root        14  0.0  0.0  12396  5888 ?        S    08:15   0:00 /usr/sbin/xrdp --nodaemon
root        29  0.0  0.0  12736  2100 ?        S    08:21   0:00 /usr/sbin/xrdp --nodaemon
root        30  0.0  0.0  12668  2100 ?        S    08:21   0:00 /usr/sbin/xrdp --nodaemon
root        31  0.0  0.0  12668  2100 ?        S    08:22   0:00 /usr/sbin/xrdp --nodaemon
root        38  0.0  0.0  12668  2100 ?        S    08:22   0:00 /usr/sbin/xrdp --nodaemon
```

**Analysis:**
- Main `xrdp` process (PID 14) is running
- `xrdp-sesman` (session manager, PID 13) is running
- Multiple child `xrdp` processes (PIDs 29, 30, 31, 38) indicate connection attempts
- Child processes are short-lived, suggesting they spawn but fail to establish sessions

**Conclusion:** XRDP is receiving connection attempts but failing during session setup.

---

### 3. DBus Failure: ❌ ROOT CAUSE

**Evidence:**
```bash
# Pod startup logs show DBus failure
$ kubectl logs -n octolab-labs -l app=octobox-beta
Starting DBus...
dbus[10]: Failed to start message bus: Failed to open "/usr/share/dbus-1/system.conf": No such file or directory

# Confirmation: system.conf is missing
$ kubectl exec -n octolab-labs $POD -- ls -la /usr/share/dbus-1/system.conf
ls: cannot access '/usr/share/dbus-1/system.conf': No such file or directory
```

**Root Cause Analysis:**

1. **Missing Package:** Dockerfile installs `dbus-x11` but NOT `dbus` package
   - `dbus-x11` provides DBus client libraries for X11 applications
   - `dbus` package provides the DBus daemon and system configuration files
   - Without `dbus`, `/usr/share/dbus-1/system.conf` is missing

2. **Wrong DBus Mode:** Entrypoint script attempts to start DBus as system bus:
   ```bash
   dbus-daemon --system --fork
   ```
   - System bus requires `/usr/share/dbus-1/system.conf` (missing)
   - In containers, session bus is more appropriate and doesn't require system.conf
   - XFCE can work with session bus

3. **Impact:** Without DBus:
   - XFCE cannot start (requires DBus for inter-process communication)
   - XRDP connects but `startwm.sh` → `startxfce4` fails silently
   - Connection hangs waiting for desktop session that never starts

---

### 4. XRDP Logging: ❌ LOGS NOT AVAILABLE

**Evidence:**
```bash
$ kubectl exec -n octolab-labs $POD -- cat /var/log/xrdp/xrdp.log
cat: /var/log/xrdp/xrdp.log: No such file or directory

$ kubectl exec -n octolab-labs $POD -- cat /var/log/xrdp/xrdp-sesman.log
cat: /var/log/xrdp/xrdp-sesman.log: No such file or directory
```

**Analysis:**
- Log directories exist (`/var/log/xrdp` is created in Dockerfile)
- Log files are not being created
- Possible causes:
  - XRDP not configured to log (default config issue)
  - Permissions issue (though directory is owned by xrdp:xrdp)
  - XRDP failing before logging starts

**Impact:** Cannot see detailed error messages from XRDP about why sessions fail.

---

### 5. Configuration Files

**XRDP Start Script:**
```bash
$ kubectl exec -n octolab-labs $POD -- cat /etc/xrdp/startwm.sh
#!/bin/sh

if [ -r /etc/default/locale ]; then
  . /etc/default/locale
  export LANG LANGUAGE
fi

# Start XFCE session for XRDP
exec startxfce4
```

**Status:** ✅ Correct - script is properly configured to launch XFCE

---

## Root Cause Summary

**Primary Issue:** DBus system bus fails to start due to missing `/usr/share/dbus-1/system.conf`

**Failure Chain:**
1. Entrypoint tries to start DBus system bus → fails (missing config)
2. XRDP accepts connection → spawns child process
3. XRDP calls `/etc/xrdp/startwm.sh` → executes `startxfce4`
4. XFCE tries to start → requires DBus → DBus not running → XFCE fails
5. XRDP waits for desktop session → timeout → connection fails

**Secondary Issues:**
- Missing `dbus` package (only `dbus-x11` installed)
- Using system bus instead of session bus (container-inappropriate)
- XRDP logs not available for debugging

---

## Recommended Fixes

### Fix 1: Install `dbus` Package

**File:** `images/octobox-beta/Dockerfile`  
**Location:** Line 23-24

**Current:**
```dockerfile
# DBus
dbus-x11 \
```

**Change to:**
```dockerfile
# DBus
dbus \
dbus-x11 \
```

**Rationale:** `dbus` package provides the daemon and system configuration files needed for DBus to function.

---

### Fix 2: Use Session Bus Instead of System Bus

**File:** `images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`  
**Location:** Lines 12-18

**Current:**
```bash
# Start DBus (needed for XFCE)
if command -v dbus-daemon >/dev/null 2>&1; then
  echo "Starting DBus..."
  dbus-daemon --system --fork || true
else
  echo "Warning: dbus-daemon not found, XFCE may misbehave" >&2
fi
```

**Change to:**
```bash
# Start DBus (needed for XFCE)
# In containers, use session bus instead of system bus
if command -v dbus-daemon >/dev/null 2>&1; then
  echo "Starting DBus (session bus)..."
  mkdir -p /var/run/dbus
  dbus-daemon --session --fork || true
else
  echo "Warning: dbus-daemon not found, XFCE may misbehave" >&2
fi
```

**Rationale:**
- Session bus doesn't require `/usr/share/dbus-1/system.conf`
- More appropriate for containerized environments
- XFCE works with session bus

---

### Fix 3: Ensure XRDP Log Directory Permissions

**File:** `images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`  
**Location:** Lines 20-22

**Current:**
```bash
# XRDP runtime dirs
mkdir -p /var/run/xrdp /var/log/xrdp
chown -R xrdp:xrdp /var/run/xrdp /var/log/xrdp || true
```

**Change to:**
```bash
# XRDP runtime dirs
mkdir -p /var/run/xrdp /var/log/xrdp
chown -R xrdp:xrdp /var/run/xrdp /var/log/xrdp || true
chmod 755 /var/log/xrdp || true  # Ensure logs can be written
```

**Rationale:** Explicit permissions ensure XRDP can write log files.

---

## Testing Plan After Fixes

1. **Rebuild image:**
   ```bash
   docker build -t octobox-beta:dev images/octobox-beta/
   docker save octobox-beta:dev -o /tmp/octobox-beta-dev.tar
   sudo k3s ctr images import /tmp/octobox-beta-dev.tar
   ```

2. **Redeploy:**
   ```bash
   kubectl rollout restart deployment -n octolab-labs octobox-beta
   ```

3. **Verify DBus starts:**
   ```bash
   kubectl logs -n octolab-labs -l app=octobox-beta | grep -i dbus
   # Should show: "Starting DBus (session bus)..." without errors
   ```

4. **Verify DBus process:**
   ```bash
   kubectl exec -n octolab-labs $POD -- ps aux | grep dbus
   # Should show dbus-daemon process running
   ```

5. **Test RDP connection:**
   - Connect via Guacamole
   - Should see XFCE desktop instead of timeout

6. **Verify XRDP logs (if available):**
   ```bash
   kubectl exec -n octolab-labs $POD -- ls -la /var/log/xrdp/
   kubectl exec -n octolab-labs $POD -- tail -20 /var/log/xrdp/xrdp.log
   ```

---

## Additional Observations

### What's Working
- ✅ Network connectivity (Service, Endpoints, DNS resolution)
- ✅ XRDP daemon starts and listens on port 3389
- ✅ XRDP accepts TCP connections
- ✅ Kubernetes Service routing is correct
- ✅ Pod is healthy (1/1 Running)

### What's Broken
- ❌ DBus fails to start (missing system.conf)
- ❌ XFCE cannot start (requires DBus)
- ❌ XRDP sessions fail during desktop launch
- ❌ XRDP logs not available for debugging

### Configuration Status
- ✅ XRDP startwm.sh correctly configured
- ✅ User `pentester` exists with correct shell
- ✅ Evidence directory exists and is writable
- ✅ XRDP runtime directories exist

---

## Files Requiring Changes

1. **`images/octobox-beta/Dockerfile`**
   - Add `dbus` package to installation list

2. **`images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`**
   - Change DBus from system bus to session bus
   - Add explicit permissions for XRDP log directory

---

## Expected Outcome After Fixes

- DBus session bus starts successfully
- XFCE desktop launches when XRDP session is established
- Guacamole connections complete successfully
- Users see XFCE desktop in RDP session
- Command logging via `octolog-shell` works in XFCE terminal

---

## References

- XRDP Documentation: http://www.xrdp.org/
- DBus in Containers: https://www.freedesktop.org/wiki/Software/dbus/
- XFCE Requirements: https://docs.xfce.org/
- Debian Package: `dbus` vs `dbus-x11` - `dbus-x11` is a metapackage that depends on `dbus`, but in minimal installs, explicit `dbus` package is needed

---

## Appendix: Diagnostic Commands Used

```bash
# Pod status
kubectl get pods -n octolab-labs -l app=octobox-beta

# Check listening ports
kubectl exec -n octolab-labs $POD -- ss -tlnp | grep 3389

# Check processes
kubectl exec -n octolab-labs $POD -- ps aux | grep -E "xrdp|dbus"

# Check logs
kubectl logs -n octolab-labs -l app=octobox-beta

# Check service endpoints
kubectl get endpoints -n octolab-labs octobox-beta-rdp

# Test connectivity
kubectl exec -n octolab-system $GUACD_POD -- nc -zv octobox-beta-rdp.octolab-labs.svc.cluster.local 3389

# Check DBus config
kubectl exec -n octolab-labs $POD -- ls -la /usr/share/dbus-1/system.conf
```

---

**Report Generated:** 2025-11-22  
**Investigator:** Auto (Cursor AI Assistant)  
**Next Steps:** Apply fixes to Dockerfile and entrypoint script, rebuild image, redeploy, and verify

