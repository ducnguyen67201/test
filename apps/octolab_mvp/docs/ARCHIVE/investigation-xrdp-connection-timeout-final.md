> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Connection Timeout - Final Analysis

**Date:** 2025-11-22  
**Issue:** XRDP login succeeds, Xorg starts, XFCE loads, but xrdp daemon cannot connect to Xorg session via UNIX socket  
**Status:** Root cause identified - xorgxrdp module loads but communication channel not established  
**Priority:** HIGH - Blocks RDP functionality

---

## Executive Summary

After multiple fix attempts, the connection flow shows:
1. ✅ **Login successful** - User authentication works
2. ✅ **Xorg starts successfully** - X server running on display :10
3. ✅ **xorgxrdp module loads** - No more "undefined symbol" errors
4. ✅ **XFCE desktop starts** - All XFCE processes running
5. ✅ **Channel server starts** - xrdp-chansrv running
6. ❌ **XRDP main daemon cannot connect** - Repeated "Closed socket 22 (AF_UNIX)" errors
7. ❌ **Connection timeout** - After 3+ minutes, gives up with "connection problem, giving up"

**Critical Finding:** The `xorgxrdp` module loads successfully (`xorgxrdpSetup:` appears in logs), but the communication channel between the xrdp daemon and Xorg is not being established, despite all sockets existing and having correct permissions.

---

## Current State Analysis

### What's Working ✅

1. **Authentication & Session Management:**
   ```
   [20251122-12:26:10] [INFO ] login successful for user pentester on display 10
   [20251122-12:26:10] [INFO ] Session started successfully for user pentester on display 10
   ```

2. **Xorg Server:**
   - Xorg process running: `/usr/lib/xorg/Xorg :10 -auth .Xauthority -config /home/pentester/xrdp/xorg.conf -noreset -listen tcp -dpi 96`
   - Xorg socket exists: `/tmp/.X11-unix/X10` (permissions: `srwxrwxrwx`, owned by `pentester:pentester`)
   - Xorg listening on UNIX socket and TCP

3. **xorgxrdp Module:**
   - Module loads successfully: `(II) Module XORGXRDP: vendor="X.Org Foundation"`
   - No "undefined symbol" errors
   - `xorgxrdpSetup:` function called (initialization started)

4. **XFCE Desktop Environment:**
   - xfce4-session running (PID 31)
   - xfce4-panel running (PID 72)
   - xfconfd, xfce4-notifyd, panel plugins all running
   - DBus session bus active (dbus-launch running)

5. **XRDP Channel Server:**
   - xrdp-chansrv running (PID 38)
   - Channel server sockets created:
     - `/run/xrdp/sockdir/xrdp_chansrv_socket_10` (listening)
     - `/run/xrdp/sockdir/xrdpapi_10` (listening)

### What's Failing ❌

1. **XRDP Main Daemon Connection:**
   ```
   [20251122-12:26:10] [INFO ] lib_mod_connect: connecting via UNIX socket
   [20251122-12:26:14] [DEBUG] Closed socket 22 (AF_UNIX)
   [20251122-12:26:17] [DEBUG] Closed socket 22 (AF_UNIX)
   [20251122-12:26:21] [DEBUG] Closed socket 22 (AF_UNIX)
   [20251122-12:26:24] [DEBUG] Closed socket 22 (AF_UNIX)
   ```
   - Connection attempts every 3 seconds
   - Socket closes immediately after connection attempt
   - No error message explaining why connection fails

2. **Dynamic Monitor Error:**
   ```
   [20251122-12:26:10] [ERROR] dynamic_monitor_open_response: error
   [20251122-12:26:10] [ERROR] xrdp_rdp_recv: xrdp_channel_process failed
   ```
   - Occurs during initial connection setup
   - May be related to resolution negotiation

3. **Sesman Error:**
   ```
   [20251122-12:26:10] [ERROR] sesman_data_in: scp_process_msg failed
   [20251122-12:26:10] [ERROR] sesman_main_loop: trans_check_wait_objs failed, removing trans
   ```
   - Occurs during session startup
   - May indicate protocol mismatch

---

## Fixes Attempted

### Fix 1: Added xorgxrdp Module Loading
**File:** `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
**Change:** Added `Section "Module"` with `Load "xorgxrdp"`
**Result:** ✅ Module now loads (no more "undefined symbol" errors)

### Fix 2: Added GLAMOR Module Loading
**File:** `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
**Change:** Added `Load "glamoregl"` before `Load "xorgxrdp"`
**Result:** ✅ GLAMOR loads successfully, xorgxrdp no longer fails with "undefined symbol: glamor_xv_init"

### Fix 3: Fixed Xorg Config Path
**File:** `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
**Change:** Changed from relative path `xrdp/xorg.conf` to absolute path `/home/pentester/xrdp/xorg.conf`
**Result:** ✅ Xorg finds config file correctly

### Fix 4: Fixed Log File Path
**File:** `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
**Change:** Changed from relative `.xorgxrdp.%s.log` to absolute `/home/pentester/.xorgxrdp.%s.log`
**Result:** ✅ Xorg log files created in correct location

### Fix 5: Added DPI Parameter
**File:** `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
**Change:** Added `param=-dpi` and `param=96` to Xorg startup parameters
**Result:** ✅ No negative impact, DPI set correctly

### Fix 6: Added Extensions Section
**File:** `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
**Change:** Added `Section "Extensions"` with `Option "Composite" "Disable"`
**Result:** ✅ Composite extension disabled as recommended for xorgxrdp

### Fix 7: Fixed Socket Directory Permissions
**Files:** `images/octobox-beta/Dockerfile`, `images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`
**Change:** Created `/tmp/.X11-unix` with 1777 permissions, ensured home directory writable
**Result:** ✅ Sockets created with correct permissions

### Fix 8: Enabled TCP Listening
**File:** `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
**Change:** Changed `-nolisten tcp` to `-listen tcp` to allow TCP connections
**Result:** ⚠️ Xorg now listens on TCP, but connection still fails

---

## Configuration Details

### Current Xorg Startup Command
```
/usr/lib/xorg/Xorg :10 -auth .Xauthority -config /home/pentester/xrdp/xorg.conf -noreset -listen tcp -dpi 96 -logfile /home/pentester/.xorgxrdp.%s.log
```

### Current xrdp.ini [Xorg] Section
```ini
[Xorg]
name=Xorg
lib=libxup.so
username=ask
password=ask
ip=127.0.0.1
port=-1  # -1 means use UNIX socket
code=20
```

### Current xorg.conf Structure
```conf
Section "Module"
    Load "glamoregl"
    Load "xorgxrdp"
EndSection

Section "Extensions"
    Option "Composite" "Disable"
EndSection

Section "Device"
    Identifier  "DummyDevice"
    Driver      "dummy"
    VideoRam    256000
EndSection

Section "Monitor"
    Identifier  "DummyMonitor"
    HorizSync   15.0-200.0
    VertRefresh 40.0-200.0
    Modeline "1272x594" ...
    Modeline "1280x720" ...
EndSection

Section "Screen"
    Identifier  "DummyScreen"
    Device      "DummyDevice"
    Monitor     "DummyMonitor"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1920x1080" "1680x1050" ... "1272x594" ...
        Virtual 1920 1080
    EndSubSection
EndSection

Section "ServerLayout"
    Identifier  "DefaultLayout"
    Screen      "DummyScreen"
EndSection
```

---

## Root Cause Analysis

### Hypothesis 1: xorgxrdp Not Fully Initialized
**Evidence:**
- `xorgxrdpSetup:` appears in log, indicating initialization started
- No error messages after `xorgxrdpSetup:`
- No indication that initialization completed successfully

**Analysis:**
The `xorgxrdpSetup:` function is called, but there's no confirmation that the communication channel is established. The xorgxrdp module may need additional configuration or may be waiting for a connection that never comes.

### Hypothesis 2: Socket Path Mismatch
**Evidence:**
- xrdp.ini has `port=-1` (use UNIX socket)
- xrdp tries to connect via UNIX socket
- Socket `/tmp/.X11-unix/X10` exists and is listening
- Connection still fails

**Analysis:**
xorgxrdp may create a separate communication socket that xrdp should connect to, rather than the standard X11 socket. The xrdp daemon may be connecting to the wrong socket.

### Hypothesis 3: Protocol Mismatch
**Evidence:**
- `sesman_data_in: scp_process_msg failed` error
- `dynamic_monitor_open_response: error` error
- xorgxrdp version: 0.9.19-1
- xrdp version: 0.9.21.1-1+deb12u1

**Analysis:**
There may be a version mismatch or protocol incompatibility between xrdp and xorgxrdp. The SCP (Session Control Protocol) message processing failure suggests a protocol-level issue.

### Hypothesis 4: Missing xorgxrdp Device Configuration
**Evidence:**
- xorgxrdp loads as a module
- No Device section for xorgxrdp in xorg.conf
- Using dummy driver for video output

**Analysis:**
xorgxrdp may need to be configured as a device driver, not just loaded as a module. Some configurations require xorgxrdp to be the primary device driver.

### Hypothesis 5: TCP vs UNIX Socket Mismatch
**Evidence:**
- xrdp.ini configured for UNIX socket (`port=-1`)
- Xorg now listening on TCP (`-listen tcp`)
- xrdp still tries UNIX socket connection

**Analysis:**
xorgxrdp may require TCP connection even on localhost, but xrdp is configured for UNIX socket. This mismatch could prevent connection.

---

## Diagnostic Information

### Running Processes
```
root        24  /usr/sbin/xrdp-sesman --nodaemon
root        25  /usr/sbin/xrdp --nodaemon
root        28  /usr/sbin/xrdp --nodaemon (connection handler)
root        30  /usr/sbin/xrdp-sesman --nodaemon (session handler)
pentester   31  xfce4-session
pentester   32  /usr/lib/xorg/Xorg :10 ...
pentester   38  /usr/sbin/xrdp-chansrv
pentester   42  dbus-launch --exit-with-session startxfce4
pentester   54  xfconfd
pentester   72  xfce4-panel
```

### Listening Sockets
```
/tmp/.X11-unix/X10                    (UNIX socket, listening)
/run/xrdp/sockdir/xrdpapi_10          (UNIX socket, listening)
/run/xrdp/sockdir/xrdp_chansrv_socket_10  (UNIX socket, listening)
```

### Package Versions
```
xrdp: 0.9.21.1-1+deb12u1
xorgxrdp: 1:0.9.19-1
xserver-xorg-core: 2:21.1.7-3+deb12u11
xserver-xorg-video-dummy: 1:0.4.0-1
```

### Xorg Log Excerpt
```
[342490.578] (II) LoadModule: "xorgxrdp"
[342490.578] (II) Loading /usr/lib/xorg/modules/libxorgxrdp.so
[342490.578] (II) Module XORGXRDP: vendor="X.Org Foundation"
[342490.578] xorgxrdpSetup:
```

**Note:** No further xorgxrdp messages after `xorgxrdpSetup:`, suggesting initialization may be incomplete or waiting for connection.

---

## Recommended Next Steps

### Option 1: Try TCP Connection Instead of UNIX Socket
**Action:** Change xrdp.ini to use TCP connection
**Change:**
```ini
[Xorg]
...
ip=127.0.0.1
port=6000  # or 6010, 6210 (typical X11 TCP ports)
code=20
```
**Rationale:** xorgxrdp may require TCP communication, and we've enabled TCP listening on Xorg.

### Option 2: Check xorgxrdp Communication Socket
**Action:** Investigate if xorgxrdp creates a separate socket
**Commands:**
```bash
# Check for xorgxrdp-specific sockets
find /tmp /run -name "*xrdp*" -o -name "*xorgxrdp*" 2>/dev/null

# Check Xorg log for socket creation messages
grep -i "socket\|listen\|bind" ~/.xorgxrdp.10.log

# Try connecting to X11 socket manually
DISPLAY=:10 xdpyinfo
```

### Option 3: Configure xorgxrdp as Device Driver
**Action:** Add xorgxrdp device section to xorg.conf
**Change:**
```conf
Section "Device"
    Identifier  "xrdpdev"
    Driver      "xorgxrdp"
EndSection
```
**Rationale:** Some configurations require xorgxrdp to be the primary device, not just a module.

### Option 4: Check Version Compatibility
**Action:** Verify xrdp and xorgxrdp versions are compatible
**Research:** Check Debian 12 package compatibility matrix
**Potential Fix:** Upgrade/downgrade packages to matching versions

### Option 5: Enable Additional xorgxrdp Logging
**Action:** Add debug flags to Xorg startup
**Change:** Add `-verbose 10` or `-logverbose 10` to Xorg parameters
**Rationale:** May reveal why xorgxrdp communication channel isn't established

### Option 6: Test with Xvnc Instead
**Action:** Temporarily switch to Xvnc session type
**Rationale:** If Xvnc works, confirms issue is xorgxrdp-specific
**Change:** Modify xrdp.ini to use Xvnc session type

---

## Key Questions for Further Investigation

1. **Does xorgxrdp create a separate communication socket?**
   - Where should xrdp connect to communicate with xorgxrdp?
   - Is it the standard X11 socket or a separate socket?

2. **What does `xorgxrdpSetup:` actually do?**
   - Does it create sockets?
   - Does it wait for a connection?
   - What indicates successful initialization?

3. **Why does the UNIX socket connection fail silently?**
   - No error messages in logs
   - Socket exists and is listening
   - Connection closes immediately

4. **Is there a version mismatch?**
   - xrdp 0.9.21.1 vs xorgxrdp 0.9.19
   - Are these versions compatible?

5. **Does xorgxrdp need TCP even for localhost?**
   - We enabled TCP listening
   - But xrdp still uses UNIX socket
   - Should we switch xrdp to TCP?

---

## Conclusion

The xorgxrdp module loads successfully, but the communication channel between xrdp and Xorg is not being established. All components are running (Xorg, XFCE, xrdp-chansrv), but the main xrdp daemon cannot connect to the Xorg session.

The most likely causes are:
1. **Socket path mismatch** - xrdp connecting to wrong socket
2. **Protocol incompatibility** - Version mismatch or protocol error
3. **Incomplete xorgxrdp initialization** - Module loads but doesn't establish communication channel
4. **TCP vs UNIX socket mismatch** - xorgxrdp may require TCP but xrdp uses UNIX socket

**Recommended immediate action:** Try Option 1 (switch to TCP connection) as it's the quickest test and aligns with enabling TCP listening on Xorg.

---

## Files Modified (Summary)

1. `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
   - Added Module section with glamoregl and xorgxrdp
   - Added Extensions section
   - Configured dummy driver, monitor, screen, layout

2. `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
   - Changed config path to absolute
   - Changed log path to absolute
   - Added DPI parameter
   - Changed `-nolisten tcp` to `-listen tcp`

3. `images/octobox-beta/Dockerfile`
   - Added xorgxrdp package
   - Added xserver-xorg-video-dummy package
   - Created /tmp/.X11-unix with proper permissions

4. `images/octobox-beta/rootfs/usr/local/bin/octobox-entrypoint.sh`
   - Added socket directory permission fixes
   - Added home directory permission fixes

---

**Report Generated:** 2025-11-22  
**Next Review:** Awaiting ChatGPT analysis and recommendations

