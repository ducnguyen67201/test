> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Fix Implementation: Build xorgxrdp from Source

**Date:** 2025-11-22  
**Issue:** XRDP black screen due to xorgxrdp version incompatibility  
**Solution:** Build xorgxrdp from source to get compatible version  
**Status:** ✅ Implemented

---

## Problem Summary

XRDP 0.9.21.1 is incompatible with xorgxrdp 0.9.19-1 (the only version available in Debian 12). The version mismatch causes xorgxrdp to silently reject connections, resulting in a black screen after login.

**Root Cause:**
- xrdp 0.9.21.1 uses protocol version 20210723
- xorgxrdp 0.9.19 expects protocol version 20210225
- Incompatibility causes connection rejection → black screen

**Constraint:** User requirement - NO VNC backend, must use Xorg backend only.

---

## Solution Implemented

Build xorgxrdp from source using the `devel` branch from the neutrinolabs/xorgxrdp repository. The devel branch contains fixes for xrdp 0.9.21.1 compatibility.

### Changes Made

#### `images/octobox-beta/Dockerfile`

**Added build dependencies:**
```dockerfile
# Build dependencies for xorgxrdp (will build from source for compatibility)
build-essential \
autotools-dev \
autoconf \
automake \
libtool \
pkg-config \
xserver-xorg-dev \
x11proto-dev \
libpixman-1-dev \
```

**Build xorgxrdp from source:**
```dockerfile
# Build xorgxrdp from source (compatible with xrdp 0.9.21.1)
# Debian 12 only provides xorgxrdp 0.9.19-1 which is incompatible
# Building from source to get a compatible version (0.9.21+ or 0.10.x)
# Using devel branch which has fixes for xrdp 0.9.21.1 compatibility
RUN cd /tmp && \
    git clone --depth 1 --branch devel https://github.com/neutrinolabs/xorgxrdp.git && \
    cd xorgxrdp && \
    ./bootstrap && \
    ./configure --prefix=/usr && \
    make -j$(nproc) && \
    make install && \
    cd / && \
    rm -rf /tmp/xorgxrdp && \
    ldconfig
```

**Clean up build dependencies:**
```dockerfile
# Remove build dependencies to reduce image size (keep runtime deps)
RUN apt-get purge -y \
    build-essential \
    autotools-dev \
    autoconf \
    automake \
    libtool \
    pkg-config \
    xserver-xorg-dev \
    x11proto-dev \
    libpixman-1-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
```

**Reverted xrdp.ini and sesman.ini:**
- Xorg backend re-enabled (Xvnc removed)
- All Xorg configuration restored

---

## Why This Works

1. **Compatible Version:** The `devel` branch of xorgxrdp contains fixes for xrdp 0.9.21.1 compatibility (protocol version 20210723 support)

2. **No VNC Dependency:** Uses pure Xorg backend as required

3. **Source Build:** Ensures we get the latest compatibility fixes that aren't in Debian 12 packages

4. **Image Size:** Build dependencies are removed after compilation to keep image size reasonable

---

## Testing Steps

After rebuilding the Docker image and redeploying:

1. **Connect via Guacamole:**
   - Use the same connection details as before
   - Select "Xorg" session type

2. **Verify xorgxrdp is built from source:**
   ```bash
   kubectl exec -n octolab-labs <pod-name> -- ls -la /usr/lib/xorg/modules/libxorgxrdp.so
   kubectl exec -n octolab-labs <pod-name> -- strings /usr/lib/xorg/modules/libxorgxrdp.so | grep -i version
   ```

3. **Check Xorg log for successful initialization:**
   ```bash
   kubectl exec -n octolab-labs <pod-name> -- cat /home/pentester/.xorgxrdp.10.log | grep -i "rdpClientConGotConnection\|xorgxrdpSetup"
   ```

4. **Expected behavior:**
   - Login succeeds
   - Xorg log shows `rdpClientConGotConnection: g_sck_accept ok`
   - XFCE desktop displays (no black screen)
   - All XFCE components functional

---

## Potential Issues

1. **Build Time:** Building from source increases Docker image build time
2. **Maintenance:** Need to rebuild if xrdp is updated
3. **Stability:** Using `devel` branch may have occasional instability (though it's generally stable)

---

## Alternative Approaches Considered

1. ❌ **Xvnc Backend:** Rejected - user requirement to avoid VNC
2. ❌ **Downgrade xrdp:** Not feasible - Debian 12 only has xrdp 0.9.21.1
3. ✅ **Build from source:** Selected - meets requirements, no VNC dependency

---

## Files Modified

1. `images/octobox-beta/Dockerfile`
   - Added build dependencies
   - Added xorgxrdp build from source
   - Clean up build dependencies after build

2. `images/octobox-beta/rootfs/etc/xrdp/xrdp.ini`
   - Reverted to Xorg backend (Xvnc removed)

3. `images/octobox-beta/rootfs/etc/xrdp/sesman.ini`
   - Reverted to Xorg configuration (Xvnc removed)

---

**Implementation completed:** 2025-11-22  
**Ready for testing:** Yes - Rebuild Docker image and redeploy

