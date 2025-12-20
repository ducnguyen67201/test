> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Fix Implementation: Switch to Xvnc Backend

**Date:** 2025-11-22  
**Issue:** XRDP black screen due to xorgxrdp version incompatibility  
**Solution:** Switch from Xorg backend to Xvnc (TigerVNC) backend  
**Status:** ✅ Implemented

---

## Problem Summary

XRDP 0.9.21.1 is incompatible with xorgxrdp 0.9.19-1 (the only version available in Debian 12). The version mismatch causes xorgxrdp to silently reject connections, resulting in a black screen after login.

**Root Cause:**
- xrdp 0.9.21.1 uses protocol version 20210723
- xorgxrdp 0.9.19 expects protocol version 20210225
- Incompatibility causes connection rejection → black screen

---

## Solution Implemented

Switched XRDP to use Xvnc (TigerVNC) backend instead of Xorg backend. Xvnc doesn't have version dependency issues and is more stable.

### Changes Made

#### 1. `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`

**Disabled Xorg backend:**
```ini
; NOTE: Xorg backend (xorgxrdp) is disabled due to version incompatibility:
; - xrdp 0.9.21.1 requires xorgxrdp 0.9.21+ or 0.10.x
; - Debian 12 only provides xorgxrdp 0.9.19-1 (incompatible)
; - Using Xvnc backend as primary solution (more stable, no version dependency)

; [Xorg]
; name=Xorg
; lib=libxup.so
; username=ask
; password=ask
; ip=127.0.0.1
; port=-1
; code=20
```

**Configured Xvnc backend:**
```ini
[Xvnc]
name=Xvnc
lib=libvnc.so
username=ask
password=ask
ip=127.0.0.1
port=-1
xserverbpp=24
code=10
```

#### 2. `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`

**Configured Xvnc session parameters:**
```ini
[Xvnc]
param=/usr/bin/Xtigervnc
param=-localhost
param=-nolisten
param=tcp
param=-geometry
param=1920x1080
param=-depth
param=24
param=-SecurityTypes
param=None
param=-rfbport
param=-1
param=-dpi
param=96
param=-logfile
param=/home/pentester/.vnc/%s.log
```

---

## Testing Steps

After rebuilding the Docker image and redeploying:

1. **Connect via Guacamole:**
   - Use the same connection details as before
   - Select "Xvnc" session type (or it will be auto-selected as the only option)

2. **Verify Xvnc is running:**
   ```bash
   kubectl exec -n octolab-labs <pod-name> -- ps aux | grep Xtigervnc
   ```

3. **Check Xvnc logs:**
   ```bash
   kubectl exec -n octolab-labs <pod-name> -- cat /home/pentester/.vnc/10.log
   ```

4. **Check XRDP logs:**
   ```bash
   kubectl exec -n octolab-labs <pod-name> -- tail -50 /var/log/xrdp.log
   ```

5. **Expected behavior:**
   - Login succeeds
   - XFCE desktop displays (no black screen)
   - All XFCE components functional

---

## Benefits of Xvnc Backend

1. **No version dependencies:** Xvnc doesn't require a matching xorgxrdp version
2. **Stability:** Xvnc is well-tested and widely used
3. **Compatibility:** Works with any xrdp version
4. **Performance:** Similar performance to Xorg backend for most use cases

---

## Rollback (if needed)

To revert to Xorg backend (if compatible version becomes available):

1. Uncomment `[Xorg]` section in `xrdp.ini`
2. Comment out or remove `[Xvnc]` section
3. Rebuild and redeploy

---

## Files Modified

1. `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`
   - Disabled Xorg backend (commented with explanation)
   - Configured Xvnc backend

2. `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
   - Configured Xvnc session parameters

3. `docs/investigation-xrdp-black-screen-xorgxrdp-connection.md`
   - Updated with validated root cause
   - Documented fix implementation

---

**Implementation completed:** 2025-11-22  
**Ready for testing:** Yes - Rebuild Docker image and redeploy

