> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Investigation Report: XRDP Input Devices Not Working

**Date:** 2025-11-23  
**Issue:** XRDP desktop displays successfully but mouse and keyboard input are not working  
**Status:** Root cause identified - Input devices not explicitly configured in xorg.conf  
**Priority:** HIGH - Blocks user interaction with desktop

---

## Executive Summary

After successfully resolving the black screen issue by:
1. Building xorgxrdp from source (compatible with xrdp 0.9.21.1)
2. Switching from `dummy` driver to `xrdpdev` driver

The desktop now displays correctly, but **mouse and keyboard input are completely non-functional**. Users cannot click, type, or interact with the desktop.

---

## Current State Analysis

### What's Working ✅

1. **Desktop Display:**
   - XFCE desktop environment displays correctly
   - All visual elements visible (icons, dock, panels)
   - Screen resolution correct (1528x737 as requested by client)

2. **xorgxrdp Initialization:**
   - `rdpScreenInit` completes successfully
   - `rdpClientConInit` initializes
   - Communication channel established
   - Input messages being received: `rdpClientConProcessMsgClientInput: invalidate x 0 y 0 cx 1528 cy 737`

3. **Input Drivers Installed:**
   - `xrdpmouse_drv.so` present at `/usr/lib/xorg/modules/input/xrdpmouse_drv.so`
   - `xrdpkeyb_drv.so` present at `/usr/lib/xorg/modules/input/xrdpkeyb_drv.so`

### What's Failing ❌

1. **Input Devices Not Loaded:**
   - Xorg log shows: `(II) The server relies on udev to provide the list of input devices`
   - No `xrdpmouse` or `xrdpkeyb` drivers loaded
   - No input devices initialized

2. **User Interaction:**
   - Mouse clicks not registering
   - Keyboard input not working
   - No pointer movement

---

## Detailed Log Analysis

### Xorg Log (`/home/pentester/.xorgxrdp.10.log`)

**Input Device Detection:**
```
[394866.034] (II) The server relies on udev to provide the list of input devices.
	If no devices become available, reconfigure udev or disable AutoAddDevices.
```

**Input Messages Received (but not processed):**
```
[394866.128] rdpClientConProcessMsgClientInput: invalidate x 0 y 0 cx 1528 cy 737
[394916.915] rdpClientConProcessMsgClientInput: invalidate x 0 y 0 cx 1528 cy 737
```

**Analysis:**
- Xorg is waiting for udev to provide input devices
- In containerized environments, udev may not work properly
- Input messages are being received from xrdp but not processed because no input devices are loaded
- `xrdpmouse` and `xrdpkeyb` drivers exist but are not being loaded automatically

### XRDP Log (`/var/log/xrdp.log`)

**Input-Related Messages:**
- No specific input errors in xrdp.log
- Connection established successfully
- Input messages being sent (inferred from Xorg log)

---

## Root Cause Analysis

### Primary Issue: Missing Input Device Configuration

**Problem:** Xorg relies on udev to automatically detect and configure input devices. In containerized environments:
1. udev may not be running or may not have access to hardware devices
2. Virtual input devices (xrdpmouse, xrdpkeyb) are not physical hardware, so udev won't detect them
3. Input drivers must be explicitly configured in `xorg.conf`

**Why This Happens:**
- Modern Xorg uses udev for automatic device detection
- xrdpmouse and xrdpkeyb are virtual input drivers, not physical devices
- Without explicit configuration, Xorg doesn't know to load them
- Result: No input devices = no mouse/keyboard functionality

---

## Recommended Fix

### Solution: Add Explicit InputDevice Sections to xorg.conf

**Action:** Add `InputDevice` sections for `xrdpmouse` and `xrdpkeyb` and reference them in `ServerLayout`.

**Implementation:**

1. **Add InputDevice sections:**
```conf
Section "InputDevice"
    Identifier  "xrdpKeyboard"
    Driver      "xrdpkeyb"
    Option      "CoreKeyboard"
EndSection

Section "InputDevice"
    Identifier  "xrdpMouse"
    Driver      "xrdpmouse"
    Option      "CorePointer"
EndSection
```

2. **Update ServerLayout to reference input devices:**
```conf
Section "ServerLayout"
    Identifier  "DefaultLayout"
    Screen      "xrdpScreen"
    InputDevice "xrdpKeyboard" "CoreKeyboard"
    InputDevice "xrdpMouse" "CorePointer"
EndSection
```

**Why This Works:**
- Explicitly tells Xorg to load xrdpmouse and xrdpkeyb drivers
- Bypasses udev dependency for input device detection
- Works in containerized environments where udev may not function
- Standard configuration for xorgxrdp setups

**Risk:** Low - This is the standard configuration for xorgxrdp

---

## Alternative Solutions (if primary fix doesn't work)

### Option 1: Disable AutoAddDevices

If explicit InputDevice sections don't work, disable automatic device detection:

```conf
Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoEnableDevices" "false"
EndSection
```

**Risk:** Medium - May prevent other devices from working

### Option 2: Install xserver-xorg-input-all

Ensure all input drivers are available:

```bash
apt-get install xserver-xorg-input-all
```

**Risk:** Low - Adds more drivers but shouldn't hurt

### Option 3: Configure udev (if needed)

If udev is available but not working:

```bash
# Add user to input group
usermod -aG input pentester

# Create udev rule for uinput
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' > /etc/udev/rules.d/70-xrdp-uinput.rules
```

**Risk:** Low - May not be necessary if explicit config works

---

## Diagnostic Commands

To verify input devices are loaded after fix:

```bash
# Check if input drivers are loaded
cat /home/pentester/.xorgxrdp.10.log | grep -i "xrdpmouse\|xrdpkeyb\|using input driver"

# Check for input device initialization
cat /home/pentester/.xorgxrdp.10.log | grep -i "input.*device\|corepointer\|corekeyboard"

# List available input drivers
ls -la /usr/lib/xorg/modules/input/ | grep xrdp
```

---

## Expected Behavior After Fix

1. **Xorg Log Should Show:**
   ```
   (II) Using input driver 'xrdpmouse' for 'xrdpMouse'
   (II) Using input driver 'xrdpkeyb' for 'xrdpKeyboard'
   ```

2. **User Experience:**
   - Mouse pointer moves when moving mouse in client
   - Mouse clicks register
   - Keyboard input works
   - All desktop interactions functional

---

## Files Modified

1. `images/octobox-beta/rootfs/home/pentester/xrdp/xorg.conf`
   - Added `InputDevice` section for `xrdpKeyboard`
   - Added `InputDevice` section for `xrdpMouse`
   - Updated `ServerLayout` to reference input devices

---

## Conclusion

The input devices (mouse and keyboard) are not working because Xorg is relying on udev to automatically detect them, but in a containerized environment, udev doesn't detect the virtual xrdpmouse/xrdpkeyb drivers. The solution is to explicitly configure these input devices in `xorg.conf`.

**Recommended immediate action:** Add explicit `InputDevice` sections to `xorg.conf` and reference them in `ServerLayout`. This is the standard configuration for xorgxrdp and should resolve the input issues.

---

**Investigation completed:** 2025-11-23  
**Fix implemented:** 2025-11-23 - Added InputDevice sections to xorg.conf  
**Next action:** Rebuild Docker image and test input functionality

