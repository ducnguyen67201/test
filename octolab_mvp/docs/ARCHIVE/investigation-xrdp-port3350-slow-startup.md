> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Port 3350 and Slow Startup

**Date:** 2025-11-22  
**Issue:** User reports concern about port 3350 (unexpected) and extremely slow window appearance after RDP connection  
**Status:** Investigating

---

## Executive Summary

Two issues reported:
1. **Port 3350 concern**: User noticed port 3350 in logs/connection info and doesn't recall it being mentioned
2. **Slow startup**: Window takes "ridiculously long time" to appear after RDP connection

**Findings:**
- Port 3350 is the **default internal port** for `xrdp-sesman` (session manager)
- Port 3350 is **NOT exposed externally** - it only listens on `127.0.0.1` (localhost)
- This is **standard XRDP behavior** and was not configured by us
- Slow startup likely due to Xorg/XFCE initialization delays or network latency

---

## 1. Port 3350 Analysis

### 1.1 What is Port 3350?

Port 3350 is the **default port** used by `xrdp-sesman` (XRDP Session Manager). This is a **standard XRDP component**, not something we configured.

**Configuration Location:**
```
/etc/xrdp/sesman.ini:
  ListenAddress=127.0.0.1
  ListenPort=3350
```

### 1.2 Is Port 3350 Exposed?

**No.** Port 3350 is **internal only** and listens exclusively on `127.0.0.1` (localhost).

**Verification:**
```bash
# Inside pod:
ss -tlnp | grep 3350
# Output:
LISTEN 0 2 [::1]:3350 [::]:* users:(("xrdp-sesman",pid=16,fd=10))
```

**Key Points:**
- Port 3350 is **NOT exposed** in Kubernetes Service (only port 3389 is exposed)
- Port 3350 is **NOT accessible** from outside the pod
- Port 3350 is used for **internal communication** between `xrdp` (port 3389) and `xrdp-sesman` (port 3350)

### 1.3 XRDP Architecture

```
Client (Guacamole)
    ↓ (RDP protocol, port 3389)
xrdp daemon (port 3389, external)
    ↓ (internal, port 3350)
xrdp-sesman (port 3350, localhost only)
    ↓ (starts Xorg session)
Xorg + XFCE
```

**Why Port 3350 Exists:**
- `xrdp` (port 3389) handles RDP protocol connections from clients
- `xrdp-sesman` (port 3350) manages X sessions (Xorg, Xvnc, etc.)
- This separation allows `xrdp` to handle multiple sessions while `xrdp-sesman` manages the actual desktop sessions

### 1.4 Did We Configure This?

**No.** Port 3350 is the **default** in the standard XRDP package (`xrdp` from Debian repositories). We did not modify `sesman.ini` to change this port.

**Evidence:**
- No custom `sesman.ini` in `images/octobox-beta/rootfs/etc/xrdp/`
- Only custom file is `xrdp.ini` (which we created to disable `allow_multimon`)
- `sesman.ini` uses Debian package defaults

---

## 2. Slow Startup Analysis

### 2.1 Reported Symptom

User reports: "took a ridiculously long time for the window to show"

### 2.2 Potential Causes

#### A. Xorg Initialization Delays

**Possible Issues:**
- Xorg startup with dummy driver may take time to initialize
- Xorg config parsing and driver loading
- RANDR extension initialization

**Current Xorg Config:**
- Using dummy driver with multiple resolution modes
- Virtual size: 1920x1080
- Multiple modelines defined

**Check:**
```bash
# Xorg log timing (if session exists):
cat ~/.xorgxrdp.10.log | head -5
# Should show timestamps for initialization
```

#### B. XFCE Startup Delays

**Possible Issues:**
- XFCE session initialization
- DBus session bus creation (`dbus-launch`)
- XFCE panel/plugins loading
- First-time user profile creation

**Current Startup Script:**
```bash
# /etc/xrdp/startwm.sh
exec dbus-launch --exit-with-session startxfce4
```

**Potential Delays:**
- `dbus-launch` creates a new DBus session (may take 1-2 seconds)
- `startxfce4` loads XFCE components (panel, plugins, etc.)

#### C. Network Latency

**Possible Issues:**
- Guacamole → XRDP connection latency
- RDP protocol handshake delays
- Channel negotiation (clipboard, audio, etc.)

**Check:**
- Network latency between Guacamole pod and OctoBox pod
- RDP protocol overhead

#### D. Resource Constraints

**Current Resource Limits:**
```yaml
resources:
  requests:
    cpu: "200m"
    memory: "512Mi"
  limits:
    cpu: "1000m"
    memory: "2Gi"
```

**Current Usage:**
```
CPU: 0m (idle)
Memory: 3Mi (very low)
```

**Analysis:** Resources appear sufficient, not a bottleneck.

#### E. First-Time Session Initialization

**Possible Issues:**
- First connection creates user profile (`~/.config/xfce4/`)
- XFCE generates default configuration
- May take 10-30 seconds on first connection

**Check:**
```bash
# Check if this is first connection:
ls -la ~/.config/xfce4/
# If directory is new/empty, first-time initialization is likely
```

### 2.3 Diagnostic Commands

**To Check Startup Timing:**

```bash
# 1. Check XRDP connection timing:
tail -f /var/log/xrdp.log
# Look for timestamps between:
#   - "connecting to sesman"
#   - "login successful"
#   - "started connecting"

# 2. Check Xorg startup:
cat ~/.xorgxrdp.10.log | head -10
# Check first log entry timestamp vs. connection time

# 3. Check XFCE startup:
cat ~/.xsession-errors 2>/dev/null | head -20
# May show XFCE initialization delays

# 4. Check DBus:
ps aux | grep dbus
# Verify DBus is running
```

### 2.4 Expected vs. Actual Timing

**Expected Timing (Normal):**
- RDP handshake: 1-2 seconds
- Xorg startup: 1-2 seconds
- XFCE startup: 2-5 seconds
- **Total: 4-9 seconds** from connection to desktop

**Reported Timing:**
- User reports "ridiculously long" (likely > 30 seconds)

**If > 30 seconds, likely causes:**
1. First-time XFCE profile creation (10-30 seconds)
2. Network latency/packet loss
3. Resource contention (unlikely given current usage)
4. Xorg driver initialization issues

---

## 3. Configuration Review

### 3.1 Files We Modified

**Custom Files:**
- `rootfs/etc/xrdp/xrdp.ini` - **We created this** (disabled `allow_multimon`)
- `rootfs/etc/xrdp/startwm.sh` - **We modified this** (added `dbus-launch`)
- `rootfs/home/pentester/xrdp/xorg.conf` - **We created this** (dummy driver config)

**Standard Files (Not Modified):**
- `/etc/xrdp/sesman.ini` - **Standard Debian package** (contains port 3350 default)
- `/etc/xrdp/xrdp.ini` - **We replaced this** (but port 3350 is in sesman.ini, not xrdp.ini)

### 3.2 Port 3350 Configuration

**Location:** `/etc/xrdp/sesman.ini` (standard Debian package, not modified by us)

```ini
[Globals]
ListenAddress=127.0.0.1
ListenPort=3350
```

**Why It's There:**
- Standard XRDP architecture
- Internal communication only
- Not exposed externally
- Required for XRDP to function

### 3.3 Slow Startup Configuration

**Potential Optimizations:**

1. **Pre-create XFCE profile** (reduce first-time delay):
   ```dockerfile
   # In Dockerfile, after creating pentester user:
   RUN mkdir -p /home/pentester/.config/xfce4 && \
       chown -R pentester:pentester /home/pentester/.config
   ```

2. **Reduce Xorg resolution modes** (faster initialization):
   - Current: 8 resolution modes
   - Could reduce to 2-3 common modes

3. **Optimize DBus startup**:
   - Current: `dbus-launch --exit-with-session startxfce4`
   - Could pre-start DBus in entrypoint (already done, but may not be used by XRDP sessions)

---

## 4. Recommendations

### 4.1 Port 3350

**Action:** **No action required**

**Reasoning:**
- Port 3350 is standard XRDP behavior
- Not exposed externally (localhost only)
- Required for XRDP to function
- Not a security concern

**Documentation:**
- Add note to README explaining port 3350 is internal
- Clarify that only port 3389 is exposed

### 4.2 Slow Startup

**Immediate Actions:**

1. **Check if first-time connection:**
   ```bash
   # If ~/.config/xfce4/ is new, first-time delay is expected
   # Subsequent connections should be faster
   ```

2. **Pre-create XFCE profile in image:**
   - Add to Dockerfile to pre-initialize XFCE config
   - Reduces first-time delay from 10-30s to 2-5s

3. **Monitor connection timing:**
   - Add logging to track connection → desktop timing
   - Identify specific bottleneck

4. **Optimize Xorg config:**
   - Reduce resolution modes if not needed
   - Simplify modelines

**Long-term Optimizations:**

1. **Health checks:**
   - Add readiness probe to ensure XRDP is ready before marking pod ready
   - Prevents connections before services are initialized

2. **Resource tuning:**
   - Increase CPU request if needed (currently 200m may be low for XFCE startup)

3. **Connection pooling:**
   - Keep XRDP sessions warm (future enhancement)

---

## 5. Verification Steps

### 5.1 Verify Port 3350 is Internal Only

```bash
# Inside pod:
ss -tlnp | grep 3350
# Should show: LISTEN on [::1]:3350 or 127.0.0.1:3350

# From outside pod (should fail):
nc -zv <pod-ip> 3350
# Should fail (connection refused or timeout)
```

### 5.2 Measure Startup Time

```bash
# 1. Clear any existing session:
pkill -u pentester Xorg

# 2. Connect via Guacamole and time:
time (connect and wait for desktop)

# 3. Check logs for timing:
tail -f /var/log/xrdp.log
# Note timestamps between connection and desktop appearance
```

### 5.3 Check First-Time vs. Subsequent Connections

```bash
# First connection:
ls -la ~/.config/xfce4/
# If empty/new, first-time initialization

# Subsequent connections should be faster
# Compare timing between first and second connection
```

---

## 6. Conclusion

### 6.1 Port 3350

**Status:** ✅ **Normal behavior, no action needed**

- Port 3350 is standard XRDP internal port
- Not exposed externally
- Required for XRDP functionality
- Not a security concern

### 6.2 Slow Startup

**Status:** ⚠️ **Needs investigation and optimization**

**Likely Causes:**
1. First-time XFCE profile creation (10-30 seconds)
2. Xorg/XFCE initialization delays
3. Network latency (less likely)

**Recommended Actions:**
1. Pre-create XFCE profile in Dockerfile
2. Monitor connection timing to identify bottleneck
3. Optimize Xorg config (reduce resolution modes)
4. Add health checks to ensure readiness

**Expected Improvement:**
- First connection: 10-30s → 5-10s (with pre-created profile)
- Subsequent connections: 2-5s (should already be fast)

---

## 7. Next Steps

1. **Document port 3350** in README (internal, not exposed)
2. **Pre-create XFCE profile** in Dockerfile to reduce first-time delay
3. **Add connection timing logs** to identify specific delays
4. **Test subsequent connections** to verify they're faster
5. **Consider health checks** to prevent premature connections

---

**Report Generated:** 2025-11-22  
**Investigator:** AI Assistant  
**Status:** Awaiting user feedback on findings

