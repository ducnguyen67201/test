> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: Black Screen Despite Xorg/XFCE Running

**Date:** 2025-11-22  
**Component:** OctoBox Beta (G2.2)  
**Issue:** Guacamole RDP connection shows black screen, but Xorg and XFCE are actually running  
**Status:** Root cause identified - XRDP channel server communication issue

---

## Executive Summary

After implementing Xorg dummy driver configuration (G2.2), Xorg successfully starts and creates a screen using the dummy driver. XFCE desktop environment also starts and is running. However, users still see a black screen in Guacamole. The root cause is **XRDP channel server communication failure** - the XRDP protocol bridge between the RDP client and X11 display is not properly forwarding the desktop content.

---

## Problem Statement

### Symptom
- Guacamole RDP connection establishes successfully
- User sees black screen (no desktop content)
- Connection does not timeout (stays connected)

### Environment
- **Kubernetes:** Single-node k3s cluster
- **Namespace:** `octolab-labs`
- **Image:** `octobox-beta:dev` (with G2.2 fixes applied)
- **XRDP Version:** 0.9.x (from Debian 12 repos)
- **Xorg:** 1.21.1.7 with dummy driver
- **Desktop:** XFCE 4.18+

---

## Investigation Findings

### 1. Xorg Status: ✅ WORKING

**Evidence from Xorg log (`/home/pentester/.xorgxrdp.10.log`):**

```
[335824.682] (++) Using config file: "xrdp/xorg.conf"
[335824.690] (II) LoadModule: "dummy"
[335824.691] (II) Loading /usr/lib/xorg/modules/drivers/dummy_drv.so
[335824.691] (II) DUMMY(0): Chipset is a DUMMY
[335824.691] (**) DUMMY(0): VideoRAM: 256000 kByte
[335824.691] (II) DUMMY(0): DummyMonitor: Using hsync range of 31.50-48.50 kHz
[335824.691] (II) DUMMY(0): Virtual size is 1024x768 (pitch 1024)
[335824.691] (**) DUMMY(0): *Default mode "1024x768": 65.0 MHz, 48.4 kHz, 60.0 Hz
[335824.692] (II) DUMMY(0): Output DUMMY0 using initial mode 1024x768 +0+0
[335824.693] (II) DUMMY(0): Output DUMMY0 connected
[335824.825] (II) Initializing extension GLX
[335824.825] (II) GLX: Initialized DRISWRAST GL provider for screen 0
```

**Analysis:**
- ✅ Config file loaded successfully
- ✅ Dummy driver loaded and initialized
- ✅ Screen created at 1024x768 resolution
- ✅ X server extensions initialized (GLX, RANDR, etc.)
- ✅ No fatal errors in Xorg startup

**Conclusion:** Xorg is functioning correctly with the dummy driver configuration.

---

### 2. XFCE Status: ✅ RUNNING

**Evidence from process list:**

```
pentest+    23  0.0  0.2 470528 74752 ?        Sl   10:35   0:00 xfce4-session
pentest+    24  0.1  0.2 581104 89268 ?        Sl   10:35   0:00 /usr/lib/xorg/Xorg :10
pentest+    34  0.0  0.0 10112  2080 ?        S    10:35   0:00 dbus-launch --exit-with-session startxfce4
pentest+    46  0.0  0.0 230464  5376 ?        Sl   10:35   0:00 /usr/lib/x86_64-linux-gnu/xfce4/xfconf/xfconfd
pentest+    64  0.1  0.0 412708 29776 ?        Sl   10:35   0:00 xfce4-panel
pentest+    80  0.0  0.0 257368 16896 ?        Sl   10:35   0:00 /usr/lib/x86_64-linux-gnu/xfce4/notifyd/xfce4-notifyd
```

**Analysis:**
- ✅ XFCE session manager running (PID 23)
- ✅ XFCE panel running (PID 64)
- ✅ XFCE notification daemon running (PID 80)
- ✅ DBus session bus active (via dbus-launch)
- ✅ All XFCE components appear to be running normally

**Conclusion:** XFCE desktop environment is running and should be drawing to the X display.

---

### 3. XRDP Channel Server: ❌ COMMUNICATION FAILURE

**Evidence from XRDP logs (`/var/log/xrdp.log`):**

```
[20251122-10:35:05] [INFO ] login successful for user pentester on display 10
[20251122-10:35:05] [INFO ] loaded module 'libxup.so' ok, interface size 10296, version 4
[20251122-10:35:05] [INFO ] started connecting
[20251122-10:35:05] [INFO ] lib_mod_connect: connecting via UNIX socket
[20251122-10:35:05] [ERROR] dynamic_monitor_open_response: error
[20251122-10:35:05] [ERROR] xrdp_rdp_recv: xrdp_channel_process failed
```

**Evidence from XRDP sesman logs (`/var/log/xrdp-sesman.log`):**

```
[20251122-10:35:05] [INFO ] Starting X server on display 10: /usr/lib/xorg/Xorg :10 -auth .Xauthority -config xrdp/xorg.conf -noreset -nolisten tcp -logfile .xorgxrdp.%s.log  
[20251122-10:35:05] [INFO ] Found X server running at /tmp/.X11-unix/X10
[20251122-10:35:05] [INFO ] Session started successfully for user pentester on display 10
[20251122-10:35:05] [INFO ] Starting the xrdp channel server for display 10
[20251122-10:35:05] [INFO ] Starting the default window manager on display 10: /etc/xrdp/startwm.sh
```

**Analysis:**
- ✅ X server detected and running
- ✅ Session started successfully
- ✅ Window manager (startwm.sh) started
- ❌ **XRDP channel server errors:** `dynamic_monitor_open_response: error` and `xrdp_channel_process failed`
- ❌ These errors occur **after** successful login and X server connection

**Conclusion:** The XRDP channel server (which bridges RDP protocol to X11) is failing to establish proper communication, preventing desktop content from being forwarded to the RDP client.

---

### 4. X Server Socket: ✅ EXISTS

**Evidence:**

```bash
$ ls -la /tmp/.X11-unix/
srwxrwxrwx 1 pentester pentester    0 Nov 22 10:35 X10
```

**Analysis:**
- ✅ X server socket exists at `/tmp/.X11-unix/X10`
- ✅ Permissions allow access (world-readable socket)
- ✅ Socket is owned by `pentester` user

**Conclusion:** X server socket is accessible and properly configured.

---

## Root Cause Analysis

### Failure Chain

1. ✅ **XRDP accepts connection** - TLS handshake completes
2. ✅ **Authentication succeeds** - User `pentester` authenticated
3. ✅ **Xorg starts** - Dummy driver loads, screen created at 1024x768
4. ✅ **XFCE starts** - Desktop environment initializes and draws to X display
5. ❌ **XRDP channel server fails** - `dynamic_monitor_open_response: error` and `xrdp_channel_process failed`
6. ❌ **Desktop content not forwarded** - RDP client receives no screen updates
7. ❌ **User sees black screen** - Connection active but no visual content

### Key Issue: XRDP Channel Server Communication

The XRDP architecture uses a **channel server** (`xrdp_channel`) that:
- Connects to the X server via X11 protocol
- Captures screen updates and input events
- Translates between X11 and RDP protocol
- Forwards content to the RDP client

The errors `dynamic_monitor_open_response: error` and `xrdp_channel_process failed` indicate this channel server is failing to:
- Establish proper communication with the X server, OR
- Negotiate display parameters with the RDP client, OR
- Process screen updates from the X server

### Potential Causes

1. **Dynamic monitor negotiation failure** - The `dynamic_monitor_open_response: error` suggests the RDP client (Guacamole) is trying to negotiate monitor/resolution settings that Xorg with dummy driver cannot satisfy
2. **Display resolution mismatch** - Client requesting different resolution than Xorg provides (client may request 1272x594 based on sesman log, but Xorg only provides 1024x768)
3. **Monitor sync range too restrictive** - Our xorg.conf has `HorizSync 31.5-48.5` which may be rejecting client-requested resolutions
4. **xorgxrdp module issue** - The `libxup.so` module (xorgxrdp) may not be properly handling dynamic resolution changes with dummy driver
5. **XRDP channel server permissions** - Channel server may not have proper access to X server (less likely, as socket is world-readable)

### Additional Diagnostic Findings

**Channel server status:**
- ✅ `xrdp-chansrv` process is running (PID 30)
- ✅ Channels are enabled in `/etc/xrdp/xrdp.ini` (`allow_channels=true`)
- ✅ All standard channels enabled (rdpdr, rdpsnd, cliprdr, etc.)

**Resolution mismatch:**
- XRDP sesman log shows: `width 1272, height 594` (client-requested)
- Xorg config provides: `1024x768` (fixed resolution)
- This mismatch may cause `dynamic_monitor_open_response` to fail

---

## Diagnostic Evidence Summary

### What's Working ✅
- Xorg starts successfully with dummy driver
- Screen created at 1024x768 resolution
- XFCE desktop environment running
- X server socket accessible
- DBus session bus active
- RDP connection establishes (TLS, authentication)

### What's Broken ❌
- XRDP channel server communication (`dynamic_monitor_open_response: error`)
- Desktop content not forwarded to RDP client
- User sees black screen despite desktop running

### Configuration Status
- ✅ Xorg config file exists and is loaded
- ✅ Dummy driver configured correctly
- ✅ XRDP sesman starts Xorg correctly
- ✅ Window manager (startwm.sh) launches XFCE
- ⚠️ XRDP channel server failing (needs investigation)

---

## Recommended Next Steps

### Immediate Investigation

1. **Check for xrdp_channel process:**
   ```bash
   kubectl exec -n octolab-labs $POD -- ps aux | grep xrdp_channel
   ```

2. **Check XRDP channel server logs:**
   ```bash
   kubectl exec -n octolab-labs $POD -- find /var/log -name "*channel*" -o -name "*xrdp*" | xargs tail -50
   ```

3. **Verify xorgxrdp module compatibility:**
   ```bash
   kubectl exec -n octolab-labs $POD -- dpkg -l | grep xrdp
   kubectl exec -n octolab-labs $POD -- ls -la /usr/lib/xrdp/*.so
   ```

4. **Test X server accessibility from channel server context:**
   ```bash
   kubectl exec -n octolab-labs $POD -- DISPLAY=:10 xdpyinfo
   ```

### Potential Fixes

1. **Check xorgxrdp version compatibility** - May need to update or configure xorgxrdp for dummy driver
2. **Verify channel server permissions** - Ensure channel server can access X server socket
3. **Check XRDP configuration** - May need to adjust `xrdp.ini` or `sesman.ini` for dummy driver
4. **Test with different resolution** - Client may be requesting unsupported resolution
5. **Review xorgxrdp documentation** - May need specific configuration for headless/dummy setups

---

## Additional Observations

### Monitor Sync Range Issue

The Xorg log shows many modes being rejected due to sync range constraints:

```
(II) DUMMY(0): Not using default mode "1024x768" (hsync out of range)
```

However, it eventually finds a compatible mode:

```
(II) DUMMY(0): Modeline "1024x768"x60.0   65.00  1024 1048 1184 1344  768 771 777 806 -hsync -vsync (48.4 kHz UzdP)
(II) DUMMY(0): Output DUMMY0 using initial mode 1024x768 +0+0
```

**Note:** The monitor sync ranges in our config (`HorizSync 31.5-48.5`, `VertRefresh 50-70`) may be too restrictive. The 1024x768 mode at 48.4 kHz is just within range, but this could cause issues if the client requests different resolutions.

### DBus System Bus Warnings

Xorg logs show repeated DBus system bus connection errors:

```
(EE) dbus-core: error connecting to system bus: org.freedesktop.DBus.Error.FileNotFound (Failed to connect to socket /run/dbus/system_bus_socket: No such file or directory)
```

These are non-fatal (Xorg continues to work), but may indicate some Xorg extensions are trying to use system bus instead of session bus. This is expected in containers and doesn't affect functionality.

---

## Files Requiring Investigation

1. **XRDP channel server logs** - Need to locate and examine channel server specific logs
2. **xorgxrdp module configuration** - May need to check if xorgxrdp requires specific dummy driver settings
3. **XRDP sesman configuration** - May need channel server startup parameters

---

## Expected Outcome After Fix

- XRDP channel server successfully connects to X server
- Desktop content forwarded to RDP client
- User sees XFCE desktop in Guacamole (not black screen)
- Mouse and keyboard input work correctly
- Screen updates appear in real-time

---

**Report Generated:** 2025-11-22  
**Investigator:** Auto (Cursor AI Assistant)  
**Status:** Xorg and XFCE working, but XRDP channel server communication failing - need to investigate xorgxrdp module and channel server configuration

**Next Steps:**
1. Investigate xrdp_channel process status
2. Check xorgxrdp module compatibility with dummy driver
3. Review XRDP channel server configuration
4. Test X server accessibility from channel server context

