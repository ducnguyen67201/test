> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Black Screen - xorgxrdp Connection Failure

**Date:** 2025-11-22  
**Issue:** XRDP login succeeds, Xorg starts, XFCE loads, but xrdp daemon cannot connect to Xorg session - black screen persists  
**Status:** Root cause identified - xorgxrdp module loads but communication channel not established  
**Priority:** HIGH - Blocks RDP functionality

---

## Executive Summary

After multiple fix attempts, the connection flow shows:
1. ✅ **Login successful** - User authentication works
2. ✅ **Xorg starts successfully** - X server running on display :10
3. ✅ **xorgxrdp module loads** - Module loads without errors (`xorgxrdpSetup:` appears)
4. ✅ **XFCE desktop starts** - All XFCE processes running (xfce4-session, xfce4-panel, etc.)
5. ✅ **Channel server starts** - xrdp-chansrv running
6. ❌ **XRDP main daemon cannot connect** - Repeated "Closed socket 22 (AF_UNIX)" errors
7. ❌ **Connection timeout** - After 3+ minutes, gives up with "connection problem, giving up"

**Critical Finding:** The `xorgxrdp` module loads successfully (`xorgxrdpSetup:` appears in logs), but the communication channel between the xrdp daemon and Xorg is not being established, despite all sockets existing and having correct permissions.

**Version Mismatch Detected (CONFIRMED ROOT CAUSE):**
- xrdp: 0.9.21.1
- xorgxrdp: 0.9.19-1 (only version available in Debian 12)

**VALIDATED:** XRDP 0.9.21.1 introduced a protocol change (client_info version 20210723) that xorgxrdp 0.9.19 doesn't support (expects 20210225). This causes xorgxrdp to reject the connection silently, leading to the black screen. The Xorg log should show "Incompatible xrdp version detected" but may fail silently before logging this.

---

## Current State Analysis

### What's Working ✅

1. **Authentication & Session Management:**
   ```
   [20251122-13:25:14] [INFO ] login successful for user pentester on display 10
   [20251122-13:25:14] [INFO ] Session started successfully for user pentester on display 10
   ```

2. **Xorg Server:**
   - Xorg process running: `/usr/lib/xorg/Xorg :10 -auth .Xauthority -config /home/pentester/xrdp/xorg.conf -noreset -listen tcp -dpi 96`
   - Xorg socket exists: `/tmp/.X11-unix/X10` (permissions: `srwxrwxrwx`, owned by `pentester:pentester`)
   - Xorg listening on UNIX socket and TCP (port 6010)

3. **xorgxrdp Module:**
   - Module loads successfully: `(II) Module XORGXRDP: vendor="X.Org Foundation"`
   - No "undefined symbol" errors
   - `xorgxrdpSetup:` function called (initialization started)
   - GLAMOR module loaded before xorgxrdp (correct order)

4. **XFCE Desktop Environment:**
   - xfce4-session running (PID 39)
   - xfce4-panel running (PID 80)
   - xfconfd running (PID 62)
   - All XFCE components initialized

5. **Channel Server:**
   - xrdp-chansrv running (PID 46)
   - Channel server sockets created: `/run/xrdp/sockdir/xrdp_chansrv_socket_10`

### What's Failing ❌

1. **UNIX Socket Connection:**
   ```
   [20251122-13:25:14] [INFO ] lib_mod_connect: connecting via UNIX socket
   [20251122-13:25:18] [DEBUG] Closed socket 22 (AF_UNIX)  # Repeated every 3 seconds
   ...
   [20251122-13:28:44] [INFO ] connection problem, giving up
   [20251122-13:28:44] [ERROR] Error connecting to user session
   ```

2. **Communication Channel:**
   - xrdp tries to connect via UNIX socket to Xorg
   - Connection attempts fail silently (no error messages)
   - Socket exists and has correct permissions, but connection never succeeds

3. **xorgxrdp Initialization:**
   - `xorgxrdpSetup:` is called, but no indication that initialization completes
   - No log messages indicating xorgxrdp is ready to accept connections
   - No communication channel established

---

## Detailed Log Analysis

### XRDP Log (`/var/log/xrdp.log`)

**Connection Flow:**
```
[20251122-13:25:14] [INFO ] login successful for user pentester on display 10
[20251122-13:25:14] [INFO ] loaded module 'libxup.so' ok, interface size 10296, version 4
[20251122-13:25:14] [INFO ] started connecting
[20251122-13:25:14] [INFO ] lib_mod_connect: connecting via UNIX socket
[20251122-13:25:18] [DEBUG] Closed socket 22 (AF_UNIX)  # First failure
... (repeated every 3 seconds for 3+ minutes)
[20251122-13:28:44] [INFO ] connection problem, giving up
[20251122-13:28:44] [ERROR] Error connecting to user session
```

**Analysis:**
- Login and module loading succeed
- Connection attempt starts immediately after login
- Connection fails silently (no error message, just socket closure)
- Retries every 3 seconds for 3+ minutes before giving up

### Sesman Log (`/var/log/xrdp-sesman.log`)

**Session Startup:**
```
[20251122-13:25:14] [INFO ] starting Xorg session...
[20251122-13:25:14] [INFO ] Starting X server on display 10: /usr/lib/xorg/Xorg :10 ...
[20251122-13:25:15] [INFO ] Found X server running at /tmp/.X11-unix/X10
[20251122-13:25:15] [INFO ] Session started successfully for user pentester on display 10
[20251122-13:25:15] [INFO ] Starting the xrdp channel server for display 10
[20251122-13:25:15] [INFO ] Starting the default window manager on display 10: /etc/xrdp/startwm.sh
```

**Analysis:**
- Sesman successfully starts Xorg
- Xorg socket is created and detected
- Session and window manager start successfully
- No errors in sesman log

### Xorg Log (`/home/pentester/.xorgxrdp.10.log`)

**Module Loading:**
```
[346035.008] (II) LoadModule: "xorgxrdp"
[346035.008] (II) Loading /usr/lib/xorg/modules/libxorgxrdp.so
[346035.009] (II) Module XORGXRDP: vendor="X.Org Foundation"
[346035.009] xorgxrdpSetup:
```

**Analysis:**
- xorgxrdp module loads successfully
- `xorgxrdpSetup:` function is called (initialization started)
- **No log messages after `xorgxrdpSetup:` indicating successful initialization**
- **No indication that xorgxrdp is ready to accept connections**

**Errors:**
```
[346035.001] (EE) dbus-core: error connecting to system bus: org.freedesktop.DBus.Error.FileNotFound
```
- DBus system bus errors (expected in container, not blocking)

---

## Root Cause Analysis

### Primary Issue: xorgxrdp Communication Channel Not Established

The `xorgxrdp` module loads successfully, but the communication channel between xrdp and Xorg is not being established. This is evidenced by:

1. **Module loads but doesn't initialize fully:**
   - `xorgxrdpSetup:` is called
   - No follow-up log messages indicating successful initialization
   - No indication that xorgxrdp is ready to accept connections

2. **Connection attempts fail silently:**
   - xrdp tries to connect via UNIX socket
   - Socket exists and has correct permissions
   - Connection closes immediately without error messages
   - Suggests xorgxrdp is not listening or not ready

3. **Version mismatch:**
   - xrdp: 0.9.21.1
   - xorgxrdp: 0.9.19
   - This version mismatch may cause protocol incompatibility

### Possible Causes

1. **Version Incompatibility:**
   - xrdp 0.9.21.1 may use a protocol version that xorgxrdp 0.9.19 doesn't support
   - Communication channel initialization may have changed between versions

2. **Incomplete xorgxrdp Initialization:**
   - `xorgxrdpSetup:` is called but initialization doesn't complete
   - Missing dependency or configuration preventing full initialization
   - Module loads but doesn't create communication channel

3. **Socket Path Mismatch:**
   - xrdp connects to `/tmp/.X11-unix/X10` (standard X11 socket)
   - xorgxrdp may create a separate communication socket
   - xrdp may be connecting to the wrong socket

4. **TCP vs UNIX Socket Mismatch:**
   - Xorg is configured to listen on TCP (`-listen tcp`)
   - xrdp is configured to use UNIX socket (`port=-1`)
   - xorgxrdp may require TCP connection even for localhost

---

## Diagnostic Information

### Installed Packages
```
ii  xorgxrdp  1:0.9.19-1      amd64  Remote Desktop Protocol (RDP) modules for X.org
ii  xrdp      0.9.21.1-1+deb12u1  amd64  Remote Desktop Protocol (RDP) server
```

### Running Processes
```
pentester  39  xfce4-session
pentester  40  /usr/lib/xorg/Xorg :10 ...
pentester  46  /usr/sbin/xrdp-chansrv
pentester  50  dbus-launch --exit-with-session startxfce4
pentester  62  /usr/lib/x86_64-linux-gnu/xfce4/xfconf/xfconfd
pentester  80  xfce4-panel
```

### Sockets
```
/tmp/.X11-unix/X10                          # Xorg UNIX socket (exists, correct permissions)
/run/xrdp/sockdir/xrdp_chansrv_socket_10    # Channel server socket (exists)
/run/xrdp/sockdir/xrdpapi_10                # API socket (exists)
```

### Configuration Files

**xrdp.ini [Xorg] section:**
```ini
[Xorg]
name=Xorg
lib=libxup.so
username=ask
password=ask
ip=127.0.0.1
port=-1  # UNIX socket
code=20
```

**sesman.ini [Xorg] section:**
```ini
[Xorg]
param=/usr/lib/xorg/Xorg
param=-config
param=/home/pentester/xrdp/xorg.conf
param=-noreset
param=-listen
param=tcp
param=-dpi
param=96
param=-logfile
param=/home/pentester/.xorgxrdp.%s.log
param=-logverbose
param=7
```

**xorg.conf Module section:**
```conf
Section "Module"
    Load "glamoregl"
    Load "xorgxrdp"
EndSection
```

---

## Fixes Attempted

1. ✅ **Added xorgxrdp package** - Module now loads
2. ✅ **Added GLAMOR module** - Required dependency for xorgxrdp
3. ✅ **Configured dummy video driver** - Xorg starts successfully
4. ✅ **Enabled TCP listening on Xorg** - Xorg listens on TCP port 6010
5. ✅ **Set DEBUG logging** - Full visibility into connection attempts
6. ✅ **Fixed DBus session bus** - XFCE starts successfully
7. ✅ **Fixed permissions** - All sockets have correct permissions
8. ❌ **UNIX socket connection** - Still fails
9. ❌ **TCP connection (port=6010)** - Tried but bypasses sesman (incorrect)

---

## Root Cause Validated ✅

**Validation Source:** User-provided research confirming:
1. Xorgxrdp initialization requires `rdpClientConGotConnection: g_sck_accept ok` in logs (missing)
2. XRDP 0.9.21.1 uses protocol version 20210723, xorgxrdp 0.9.19 expects 20210225
3. Version mismatch causes silent connection rejection
4. Communication uses custom AF_UNIX socket + shared memory (not standard X11 socket)
5. Repeated "Closed socket 22 (AF_UNIX)" indicates xorgxrdp never accepts connection

**Conclusion:** Version incompatibility confirmed as root cause. Debian 12 only provides xorgxrdp 0.9.19-1, which is incompatible with xrdp 0.9.21.1.

## Recommended Next Steps

### Option 1: Use Xvnc Backend (IMPLEMENTED - RECOMMENDED)

**Action:** Switch to Xvnc (TigerVNC) backend instead of Xorg backend.

**Why:** 
- Debian 12 only provides xorgxrdp 0.9.19-1 (incompatible with xrdp 0.9.21.1)
- Xvnc doesn't have version dependency issues
- Xvnc is more stable and widely tested
- No protocol version mismatches

**Implementation:**
1. ✅ Disabled Xorg backend in xrdp.ini (commented out with explanation)
2. ✅ Configured Xvnc backend in xrdp.ini
3. ✅ Configured Xvnc in sesman.ini with proper parameters
4. Xvnc will be used automatically as the only available session type

**Risk:** Low - Xvnc is a proven, stable backend. Minor performance difference vs Xorg backend.

**Status:** ✅ IMPLEMENTED - Ready for testing

### Option 2: Upgrade xorgxrdp to Match xrdp Version (NOT FEASIBLE)

**Action:** Upgrade xorgxrdp from 0.9.19 to 0.9.21+ or 0.10.x to match xrdp version.

**Why:** Would resolve version incompatibility if newer version available.

**Implementation:**
1. ❌ Checked Debian 12 repositories - only xorgxrdp 0.9.19-1 available
2. Would require building from source or using backports (not recommended for production)
3. Not feasible for containerized deployment

**Risk:** High - Building from source adds complexity and maintenance burden

**Status:** ❌ NOT FEASIBLE - Debian 12 doesn't provide compatible version

### Option 3: Investigate xorgxrdp Initialization

**Action:** Add more verbose logging or debugging to understand why xorgxrdp initialization doesn't complete.

**Why:** `xorgxrdpSetup:` is called but no indication that initialization completes. Need to understand what's blocking initialization.

**Implementation:**
1. Check xorgxrdp source code or documentation for initialization requirements
2. Add environment variables or configuration to enable more verbose logging
3. Check if there are missing dependencies or configuration

**Risk:** Low - Investigation only, no code changes

### Option 4: Try Alternative Connection Method

**Action:** Experiment with different connection methods (TCP vs UNIX socket, different socket paths).

**Why:** Current UNIX socket connection fails. May need to use TCP or a different socket path.

**Implementation:**
1. Try setting `port=6010` in xrdp.ini (but ensure sesman still manages session)
2. Check if xorgxrdp creates a separate communication socket
3. Verify socket paths and permissions

**Risk:** Medium - May break session management if not done correctly

### Option 5: Use Xvnc Fallback

**Action:** Switch to Xvnc backend instead of Xorg backend.

**Why:** Xvnc is more stable and doesn't require xorgxrdp module.

**Implementation:**
1. Configure Xvnc in xrdp.ini
2. Configure Xvnc in sesman.ini
3. Test connection

**Risk:** Low - Xvnc is a proven fallback, but may have performance differences

---

## Conclusion

The xorgxrdp module loads successfully, but the communication channel between xrdp and Xorg is not being established. All components are running (Xorg, XFCE, xrdp-chansrv), but the main xrdp daemon cannot connect to the Xorg session.

The most likely causes are:
1. **Version mismatch** - xrdp 0.9.21.1 vs xorgxrdp 0.9.19 causing protocol incompatibility
2. **Incomplete xorgxrdp initialization** - Module loads but doesn't establish communication channel
3. **Socket path/protocol mismatch** - xrdp using UNIX socket but xorgxrdp may require TCP

**Recommended immediate action:** ✅ **IMPLEMENTED** - Switched to Xvnc backend (Option 1). This is the most practical solution given Debian 12's package availability. Xvnc is stable, well-tested, and doesn't have version dependency issues.

---

## Files Modified (Summary)

1. `images/octobox-beta/Dockerfile`
   - Added xorgxrdp package
   - Added xserver-xorg-video-dummy package
   - Added dbus package
   - Added tigervnc-standalone-server package

2. `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
   - Added Module section with glamoregl and xorgxrdp
   - Added Extensions section
   - Configured dummy driver, monitor, screen, layout

3. `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
   - Changed config path to absolute
   - Changed log path to absolute
   - Added DPI parameter
   - Changed `-nolisten tcp` to `-listen tcp`

4. `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`
   - Set `allow_multimon=false`
   - Added Logging section with DEBUG level
   - Configured Xorg section with `port=-1` (UNIX socket)

5. `images/octobox-beta/rootfs/etc/xrdp/startwm.sh`
   - Modified to use `dbus-launch --exit-with-session startxfce4`

6. `images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`
   - Added DBus session bus startup
   - Added debug prints
   - Added runtime permissions for X11 sockets

---

**Investigation completed:** 2025-11-22  
**Root cause validated:** 2025-11-22  
**Fix implemented:** 2025-11-22 - Switched to Xvnc backend  
**Next action:** Rebuild Docker image and test Xvnc connection

