<!-- 8ce4ae0a-1d62-4f6a-8b3c-003acdf6e5d8 c16976a0-590a-48f3-9a11-be8027ca3c35 -->
# Octobox VNC Password Fix

## Diagnosis

- `tigervnc-standalone-server` brings Xtigervnc but omits the password helper; `tigervnc-tools` (or `tigervnc-common` in some distros) ships `vncpasswd`/`tigervncpasswd`, so the binary was never installed.
- Because the `apt-get install` layer was cached, rebuilding without editing the package list reused the old layer, leaving the password tool absent even after code changes.

## Implementation Plan

1. Update Dockerfile packages

- Edit `images/octobox-beta/Dockerfile` install stanza to add `tigervnc-tools` (or whichever package supplies `vncpasswd` on Debian 12).
- Touch the apt install line (e.g., re-run `apt-get update && apt-get install ...`) so the layer rebuilds and caches the new package set.

2. Ensure permissions and env defaults in entrypoint

- In `rootfs/usr/local/bin/start-vnc-session.sh`, keep `set -euo pipefail`, emit clear `echo` logs for each major action, and ensure `$HOME/.vnc` exists with 700 perms owned by `pentester` and the passwd file is 600.

3. Detect password helper explicitly

- Add logic to locate `vncpasswd` or fallback to `tigervncpasswd`, aborting with an informative error if neither exists; continue writing the password via stdin as today.

4. Make Xtigervnc startup configurable yet secure

- Allow optional env overrides like `VNC_GEOMETRY` and `VNC_LOCALHOST`, defaulting to `1280x800` and binding to localhost; ensure Xtigervnc uses those values.

5. Preserve XFCE + octolog shell flow

- Confirm the script still launches `startxfce4` under `sudo -u pentester DISPLAY=:1 dbus-launch --exit-with-session startxfce4` so XFCE Terminal inherits `/usr/local/bin/octolog-shell`.

## File Touch List

- `images/octobox-beta/Dockerfile`
- `images/octobox-beta/rootfs/usr/local/bin/start-vnc-session.sh`

## Later / TODO

- Wire TigerVNC into Apache Guacamole and expose via Kubernetes Service/NetworkPolicy.
- Replace static VNC password with per-tenant credentials sourced from the backend orchestration flow.
- Extend automated testing to cover evidence logging during GUI sessions.

### To-dos

- [ ] Add tigervnc-tools to Dockerfile install list
- [ ] Harden start-vnc-session.sh permissions logging env