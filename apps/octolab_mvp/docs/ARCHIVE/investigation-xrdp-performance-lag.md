> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Performance Lag

**Date:** 2025-11-23  
**Issue:** XRDP connection is working but feels slow and laggy despite being local  
**Status:** Investigating performance bottlenecks  
**Priority:** MEDIUM - Affects user experience

---

## Executive Summary

XRDP desktop connection is functional (display and input working), but performance is sluggish with noticeable lag. This is unexpected for a local connection. Multiple factors may be contributing:

1. **Guacamole overhead** - Connection path: Browser → Guacamole Web → guacd → XRDP (adds encoding/decoding layers)
2. **High color depth** - Currently using 32-bit color (max_bpp=32), increasing bandwidth
3. **DEBUG logging enabled** - Verbose logging adds CPU overhead
4. **Resolution mismatch** - Xorg initializes at 800x600 but client requests 1528x737, requiring dynamic resizing
5. **RemoteFX codec** - Using RemoteFX which may not be optimal for all scenarios

---

## Current State Analysis

### Connection Path

```
Browser (User)
    ↓ (HTTPS/WebSocket)
Guacamole Web (port 8080)
    ↓ (RDP protocol)
guacd (port 4822)
    ↓ (RDP protocol, local network)
XRDP (port 3389)
    ↓ (UNIX socket)
Xorg + xorgxrdp
```

**Analysis:**
- Even though pods are on the same node, there are **4 hops** in the connection path
- Each hop adds encoding/decoding overhead
- Guacamole adds significant overhead (browser-based RDP client)

### Performance Settings

**Current XRDP Configuration:**
```ini
max_bpp=32              # 32-bit color (high bandwidth)
use_fastpath=both       # ✅ Good - enables fastpath
bitmap_cache=true       # ✅ Good
bitmap_compression=true # ✅ Good
bulk_compression=true   # ✅ Good
tcp_nodelay=true        # ✅ Good
LogLevel=DEBUG          # ❌ High overhead
```

**Xorg Configuration:**
- Initial resolution: 800x600
- Client requests: 1528x737
- Dynamic resizing required
- Virtual size: 1920x1080

### Resource Usage

**Current:**
- CPU: 543m (reasonable)
- Memory: 162Mi (reasonable)

**Not a resource constraint issue.**

---

## Root Cause Analysis

### Primary Contributors to Lag

1. **Guacamole Overhead (LIKELY PRIMARY CAUSE)**
   - Browser-based RDP client adds encoding/decoding layers
   - WebSocket protocol overhead
   - JavaScript rendering in browser
   - Even on local network, Guacamole adds 50-200ms latency per frame

2. **High Color Depth**
   - `max_bpp=32` means 32-bit color (4 bytes per pixel)
   - At 1528x737 resolution: ~4.5MB per full screen update
   - Reducing to 16-bit or 24-bit would cut bandwidth in half

3. **DEBUG Logging**
   - Verbose logging to `/var/log/xrdp.log` and `/var/log/xrdp-sesman.log`
   - Every operation logged in detail
   - Adds CPU overhead and I/O latency

4. **Resolution Mismatch**
   - Xorg initializes at 800x600
   - Client requests 1528x737
   - Requires dynamic resolution change (adds delay)

5. **RemoteFX Codec**
   - Log shows: `rdpClientConProcessMsgClientInfo: got RFX capture`
   - RemoteFX is good for high-quality but may be slower than other codecs
   - No H.264/GFX codec detected (which would be faster)

---

## Recommended Fixes

### Fix 1: Reduce Color Depth (QUICK WIN)

**Action:** Reduce `max_bpp` from 32 to 16 or 24.

**Why:** 
- 16-bit: ~50% bandwidth reduction
- 24-bit: ~25% bandwidth reduction
- Minimal visual quality loss for most use cases

**Implementation:**
```ini
max_bpp=16  # or 24 for better quality
```

**Expected Improvement:** 25-50% bandwidth reduction → faster updates

### Fix 2: Disable DEBUG Logging (QUICK WIN)

**Action:** Change `LogLevel` from `DEBUG` to `INFO` or `WARN`.

**Why:**
- Reduces CPU overhead
- Reduces I/O operations
- Still provides useful error information

**Implementation:**
```ini
[Logging]
LogLevel=INFO  # or WARN
```

**Expected Improvement:** 5-10% CPU reduction, faster I/O

### Fix 3: Optimize Initial Resolution

**Action:** Set Xorg initial resolution to match common client resolution (e.g., 1280x720 or 1920x1080).

**Why:**
- Avoids dynamic resolution change delay
- Reduces resizing overhead

**Implementation:**
- Modify xorg.conf to use higher initial resolution
- Or configure sesman to start with client-requested resolution

**Expected Improvement:** Eliminates initial resizing delay

### Fix 4: Guacamole-Specific Optimizations

**Action:** Configure Guacamole RDP connection parameters for performance.

**Options:**
- Reduce color depth in Guacamole connection settings
- Enable performance optimizations
- Use lower quality settings for local connections

**Expected Improvement:** 20-40% latency reduction (Guacamole overhead)

### Fix 5: Enable H.264/GFX Codec (if available)

**Action:** Check if xrdp supports H.264 or GFX codec (faster than RemoteFX).

**Why:**
- H.264 hardware acceleration
- Better compression
- Lower CPU usage

**Expected Improvement:** 10-30% performance improvement

---

## Diagnostic Information

### Current Performance Metrics

**Connection Path:**
- Browser → Guacamole Web → guacd → XRDP → Xorg
- 4 hops, each adding latency

**Codec in Use:**
- RemoteFX (from Xorg log: `got RFX capture`)

**Resolution:**
- Initial: 800x600
- Client: 1528x737
- Virtual: 1920x1080

**Color Depth:**
- 32-bit (4 bytes per pixel)
- Bandwidth: ~4.5MB per full screen update

**Logging:**
- DEBUG level (high verbosity)

---

## Recommended Implementation Order

1. **Immediate (Quick Wins):**
   - ✅ Reduce `max_bpp` to 16 or 24
   - ✅ Change `LogLevel` to INFO
   - **Expected:** 30-50% improvement

2. **Short-term:**
   - Optimize initial resolution
   - Check Guacamole connection settings
   - **Expected:** Additional 10-20% improvement

3. **Long-term (if needed):**
   - Consider direct RDP connection (bypass Guacamole for testing)
   - Evaluate alternative remote desktop solutions
   - **Expected:** Significant improvement (but may not be feasible)

---

## Alternative: Direct RDP Connection (for comparison)

To test if Guacamole is the bottleneck:

```bash
# Port-forward XRDP directly
kubectl port-forward -n octolab-labs svc/octobox-beta-rdp 3389:3389

# Connect with native RDP client (Windows Remote Desktop, Remmina, etc.)
# This bypasses Guacamole entirely
```

**If direct RDP is fast but Guacamole is slow:**
- Confirms Guacamole is the bottleneck
- Focus optimization on Guacamole settings

**If both are slow:**
- Issue is in XRDP/Xorg configuration
- Focus on XRDP performance settings

---

## Conclusion

The lag is likely caused by a combination of:
1. **Guacamole overhead** (primary suspect - adds encoding/decoding layers)
2. **High color depth** (32-bit = high bandwidth)
3. **DEBUG logging** (adds CPU/I/O overhead)
4. **Resolution mismatch** (dynamic resizing delay)

**Recommended immediate actions:**
1. Reduce `max_bpp` to 16 or 24
2. Change `LogLevel` to INFO
3. Test direct RDP connection to isolate Guacamole impact

**Expected improvement:** 30-50% performance improvement with quick fixes.

---

**Investigation completed:** 2025-11-23  
**Fixes implemented:** 2025-11-23  
**Next action:** Test performance improvements

---

## Fixes Implemented

### ✅ Fix 1: Reduced Color Depth
- Changed `max_bpp` from 32 to 16
- **Expected:** 50% bandwidth reduction
- **File:** `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`

### ✅ Fix 2: Reduced Logging Verbosity
- Changed `LogLevel` from `DEBUG` to `INFO` in both `xrdp.ini` and `sesman.ini`
- **Expected:** 5-10% CPU reduction, faster I/O
- **Files:** 
  - `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`
  - `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`

### ⚠️ Remaining Issue: Guacamole Overhead

**Important Note:** Even with these optimizations, some lag may persist due to **Guacamole overhead**:

1. **Connection Path:** Browser → Guacamole Web → guacd → XRDP
   - Each hop adds encoding/decoding overhead
   - WebSocket protocol adds latency
   - JavaScript rendering in browser

2. **Expected Performance:**
   - With optimizations: 30-50% improvement
   - But Guacamole will still add 50-200ms latency per frame
   - This is inherent to browser-based RDP clients

3. **To Test Direct Performance:**
   ```bash
   # Port-forward XRDP directly (bypasses Guacamole)
   kubectl port-forward -n octolab-labs svc/octobox-beta-rdp 3389:3389
   
   # Connect with native RDP client (Windows Remote Desktop, Remmina, etc.)
   # This will show true XRDP performance without Guacamole overhead
   ```

**If direct RDP is fast but Guacamole is slow:**
- Confirms Guacamole is the bottleneck
- Consider optimizing Guacamole connection settings
- Or accept that browser-based RDP has inherent latency

**If both are slow:**
- Additional XRDP/Xorg optimizations needed
- May need to investigate xorgxrdp rendering performance

