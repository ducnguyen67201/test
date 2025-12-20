# OctoBox Beta Image

Debian 12-based OctoBox Beta attacker environment with XFCE desktop, XRDP server, and command logging via `octolog-shell`.

## Build

From repo root:

```bash
docker build -t octobox-beta:dev images/octobox-beta/
```

## Key Characteristics

- **User:** `pentester` / `pentester123` (MVP hack - TODO: replace with Kubernetes Secret)
- **RDP Port:** 3389
- **Evidence Directory:** `/evidence`
  - `commands.log` - PTY transcript
  - `commands.time` - Timing data for scriptreplay

## Components

- **Desktop:** XFCE 4.18+ with XFCE terminal
- **RDP Server:** XRDP listening on port 3389
  - `xrdp` daemon listens on TCP port 3389 (exposed via Kubernetes Service)
  - `xrdp-sesman` listens on `127.0.0.1:3350` internally (not exposed)
  - `xorgxrdp` package provides the Xorg backend module (required, installed explicitly)
- **Command Logging:** All interactive shells for `pentester` go through `octolog-shell` which wraps `script` command
- **Pentest Tools:** Minimal MVP set (nmap, curl, wget, git, python3, vim, nano, netcat)

### XRDP Architecture Notes

- **Port 3389**: External RDP port, exposed via `octobox-beta-rdp` Service
- **Port 3350**: Internal sesman port (`127.0.0.1` only), not exposed externally
- **xorgxrdp**: Required XRDP Xorg backend module. Installed explicitly because we use `--no-install-recommends` in the Dockerfile, which skips recommended packages.

### Evidence Collection

OctoBox Beta uses `octolog-shell` for evidence collection, which wraps the `script` command to record all interactive shell sessions. This ensures that all commands executed in terminal sessions are logged to `/evidence/commands.log` with timing data in `/evidence/commands.time`.

**Note:** Evidence collection requires interactive shells, which is why Xorg backend (not VNC-based backends) is used for this deployment.

## Xorg dummy driver config (G2.2)

OctoBox Beta ships an Xorg config for headless XRDP sessions:

- Path in image: `/home/pentester/xrdp/xorg.conf`
- Uses the `dummy` video driver with a default resolution of `1024x768`.
- This file is referenced indirectly via XRDP sesman (`-config xrdp/xorg.conf`).

This avoids the "no screens found" / black screen issue when running Xorg in a container.

## Testing After Rebuild

After rebuilding the image, use these commands to verify and test:

```bash
# From repo root

# 1. Rebuild image
docker build -t octobox-beta:dev images/octobox-beta/

# 2. Import into k3s
docker save octobox-beta:dev -o /tmp/octobox-beta-dev.tar
sudo k3s ctr images import /tmp/octobox-beta-dev.tar
rm /tmp/octobox-beta-dev.tar

# 3. Restart deployment
kubectl rollout restart deployment -n octolab-labs octobox-beta
kubectl rollout status deployment -n octolab-labs octobox-beta

# 4. Check startup logs
POD=$(kubectl get pod -n octolab-labs -l app=octobox-beta -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n octolab-labs "$POD"

# 5. Verify xorgxrdp is installed:
kubectl exec -n octolab-labs "$POD" -- dpkg -l | grep xorgxrdp

# 6. Try a new connection and then inspect logs:
kubectl exec -n octolab-labs "$POD" -- tail -50 /var/log/xrdp.log
kubectl exec -n octolab-labs "$POD" -- tail -50 /var/log/xrdp-sesman.log
kubectl exec -n octolab-labs "$POD" -- su - pentester -c 'tail -50 ~/.xorgxrdp.10.log || echo "no xorg log"'
kubectl exec -n octolab-labs "$POD" -- su - pentester -c 'tail -50 ~/.xsession-errors || echo "no xsession-errors yet"'
```

## TODOs

- Replace hardcoded password with Kubernetes Secret-driven configuration
- Add health checks and automated tests
- Add SSH server for key-based authentication (future)

