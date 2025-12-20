> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP UNIX Socket Connection Timeout

**Date:** 2025-11-22  
**Issue:** XRDP login succeeds but connection to user session fails with timeout  
**Status:** Root cause identified

---

## Executive Summary

After installing `xorgxrdp` and enabling DEBUG logging, the connection flow shows:
1. ✅ Login successful (`login successful for user pentester on display 10`)
2. ✅ Xorg starts successfully (`Found X server running at /tmp/.X11-unix/X10`)
3. ✅ XFCE starts successfully (xfce4-session, xfce4-panel processes running)
4. ✅ Channel server sockets created (`/run/xrdp/sockdir/xrdp_chansrv_socket_10`)
5. ❌ **XRDP main daemon cannot connect to the session via UNIX socket** (timeout after 3+ minutes)

**Root Cause:** The `xrdp` main daemon (running as root) is trying to connect to the Xorg session via a UNIX socket, but the connection attempt fails repeatedly. The socket exists and has correct permissions, but the connection never succeeds.

---

## Detailed Analysis

### 1. Connection Flow (from logs)

**XRDP Log (`/var/log/xrdp.log`):**
```
[11:56:00] [INFO ] connecting to sesman on 127.0.0.1:3350
[11:56:00] [INFO ] sesman connect ok
[11:56:00] [INFO ] login successful for user pentester on display 10
[11:56:00] [INFO ] loaded module 'libxup.so' ok, interface size 10296, version 4
[11:56:00] [INFO ] started connecting
[11:56:00] [INFO ] lib_mod_connect: connecting via UNIX socket
[11:56:03] [DEBUG] Closed socket 22 (AF_UNIX)  # Repeated every 3 seconds
...
[11:59:30] [INFO ] connection problem, giving up
[11:59:30] [INFO ] Error connecting to user session
```

**Sesman Log (`/var/log/xrdp-sesman.log`):**
```
[11:56:00] [INFO ] Starting X server on display 10: /usr/lib/xorg/Xorg :10 ...
[11:56:00] [INFO ] Found X server running at /tmp/.X11-unix/X10
[11:56:00] [INFO ] Session started successfully for user pentester on display 10
[11:56:00] [INFO ] Starting the xrdp channel server for display 10
[11:56:00] [INFO ] Starting the default window manager on display 10: /etc/xrdp/startwm.sh
```

### 2. What's Working

✅ **Authentication:** Login succeeds  
✅ **Xorg Startup:** Xorg starts and creates `/tmp/.X11-unix/X10`  
✅ **XFCE Startup:** XFCE session starts (xfce4-session, xfce4-panel running)  
✅ **Channel Server:** `xrdp-chansrv` starts and creates sockets  
✅ **Sockets Created:** `/run/xrdp/sockdir/xrdp_chansrv_socket_10` exists

### 3. What's Failing

❌ **UNIX Socket Connection:** `lib_mod_connect: connecting via UNIX socket` fails  
❌ **Socket 22:** Repeatedly closes every 3 seconds (connection retry)  
❌ **Timeout:** After 3+ minutes, gives up with "connection problem, giving up"

### 4. Socket Analysis

**Sockets Found:**
```bash
/run/xrdp/sockdir/xrdp_chansrv_socket_10  # Channel server socket
/run/xrdp/sockdir/xrdpapi_10              # API socket
/tmp/.X11-unix/X10                        # Xorg socket
```

**Socket Permissions:**
```
srw-rw---- 1 pentester root 0 Nov 22 11:56 xrdp_chansrv_socket_10
srw-rw---- 1 pentester root 0 Nov 22 11:56 xrdpapi_10
srwxrwxrwx 1 pentester pentester 0 Nov 22 11:56 X10
```

**Analysis:**
- Sockets are owned by `pentester:root` with `srw-rw----` permissions
- `xrdp` daemon runs as `root`, so it should be able to access them
- However, the connection still fails

### 5. Process Status

**Running Processes:**
```
pentester  27  xfce4-session
pentester  28  /usr/lib/xorg/Xorg :10 ...
pentester  38  dbus-launch --exit-with-session startxfce4
pentester  50  xfconfd
pentester  68  xfce4-panel
```

**Missing:**
- No `xrdp-chansrv` process visible in `ps aux` output (may have exited or be running as different user)

### 6. Configuration Check

**xrdp.ini [Xorg] section:**
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

**sesman.ini [Xorg] section:**
```ini
param=/usr/lib/xorg/Xorg
param=-config
param=xrdp/xorg.conf
param=-noreset
param=-nolisten
param=tcp
param=-logfile
param=.xorgxrdp.%s.log
```

---

## Root Cause Identified

**CRITICAL FINDING:** The `xorgxrdp` extension module is **NOT being loaded** in Xorg!

**Evidence:**
1. ✅ xorgxrdp modules exist: `/usr/lib/xorg/modules/libxorgxrdp.so`
2. ✅ Xorg starts successfully
3. ❌ **Xorg log shows NO xorgxrdp module loading** - only glx, dummy, fb, ramdac are loaded
4. ❌ **No xorgxrdp extension initialization** in Xorg log

**Why This Causes the Timeout:**
- `xrdp` tries to connect via UNIX socket to communicate with Xorg
- But Xorg doesn't have the `xorgxrdp` extension loaded, so there's no communication channel
- The socket exists and is listening, but Xorg can't respond because the extension isn't loaded
- Result: Connection timeout after 3+ minutes

**The Missing Piece:**
The `xorgxrdp` module should be automatically loaded when Xorg is started by `xrdp-sesman`, but it's not happening. This is likely because:
1. The module needs to be explicitly loaded in `xorg.conf`, OR
2. There's a configuration issue with how `xrdp-sesman` starts Xorg

---

## Diagnostic Commands

To further diagnose, check:

```bash
# 1. Check if xrdp-chansrv is actually running:
ps aux | grep xrdp-chansrv

# 2. Check socket state (listening vs. not):
ss -lx | grep xrdp

# 3. Check Xorg log for errors:
cat ~/.xorgxrdp.10.log | grep -i error

# 4. Try manual socket connection test:
nc -U /run/xrdp/sockdir/xrdp_chansrv_socket_10

# 5. Check if socket directory permissions are correct:
ls -ld /run/xrdp/sockdir/
```

---

## Recommended Fix

### Fix: Load xorgxrdp Module in xorg.conf

The `xorgxrdp` extension must be explicitly loaded in the Xorg configuration file. Add a `Module` section to `/home/pentester/xrdp/xorg.conf`:

```conf
Section "Module"
    Load "xorgxrdp"
EndSection
```

**Why This Is Needed:**
- When Xorg is started by `xrdp-sesman`, it should automatically load xorgxrdp, but it's not happening
- Explicitly loading it in `xorg.conf` ensures the module is always loaded
- Without this module, Xorg cannot communicate with xrdp via the UNIX socket

**Additional Modules to Consider:**
- `xrdpmouse` - Mouse input driver
- `xrdpkeyb` - Keyboard input driver  
- `xrdpdev` - Device driver

These may also need to be explicitly loaded if they're not auto-loading.

---

## Next Steps

1. **Add Module section to xorg.conf:** Load `xorgxrdp` explicitly
2. **Rebuild and test:** Verify xorgxrdp module loads in Xorg log
3. **Check for additional modules:** May need to load xrdpmouse, xrdpkeyb, xrdpdev
4. **Verify connection:** After module loads, xrdp should be able to connect successfully

---

**Report Generated:** 2025-11-22  
**Investigator:** AI Assistant  
**Status:** Root cause identified - UNIX socket connection timeout between xrdp and xorgxrdp session

