# OctoBox Image Provenance & Cmdlog Verification

This document explains how OctoBox image builds work, how to verify that running containers match the repo, and how to troubleshoot common issues.

## Overview

OctoBox is the attacker-box container in OctoLab labs. It includes:

- **Command logging scripts** (`/etc/profile.d/octolab-cmdlog.sh`) that record user commands to `/evidence/tlog/`
- **Build markers** (`/etc/octolab-cmdlog.build-id`, `/etc/octolab-image.build-id`) that prove which image version is running

The Docker build uses layer caching for efficiency. Heavy layers (apt-get, XFCE desktop) are cached, while cmdlog scripts can be rebuilt quickly using the `CMDLOG_BUST` build arg.

## Build Context Architecture

```
octolab-hackvm/docker-compose.yml
    └── build.context: ../images/octobox-beta
                           └── Dockerfile (correct one)
                           └── rootfs/
                               ├── etc/profile.d/octolab-cmdlog.sh
                               ├── etc/octolab-cmdlog.sh
                               └── usr/local/bin/octolog-shell
```

**Important**: The compose file builds from `images/octobox-beta/`, NOT from `octolab-hackvm/`. The `octolab-hackvm/` directory contains a legacy Dockerfile that should not be used.

## Verification Commands

### Quick Check: Is my container running the right image?

```bash
# Check build markers
docker exec <container> cat /etc/octolab-cmdlog.build-id
docker exec <container> cat /etc/octolab-image.build-id

# Check cmdlog script is installed (should show octolab-cmdlog.sh, NOT octolog.sh)
docker exec <container> ls -la /etc/profile.d/ | grep -E 'octolab-cmdlog|octolog'

# Verify PROMPT_COMMAND is installed in interactive shell
docker exec -it <container> bash -ic 'declare -p PROMPT_COMMAND; type __octo_log_prompt'
```

### Full Provenance Verification

```bash
# Run automated verification (builds, tests, cleans up)
make dev-provenance
```

This will:
1. Build OctoBox with a fresh `CMDLOG_BUST` value
2. Start a test container
3. Verify build markers match
4. Verify cmdlog scripts are correctly installed
5. Verify `PROMPT_COMMAND` includes `__octo_log_prompt`
6. Clean up

## Forcing Cmdlog Rebuild

When you modify cmdlog scripts and want to test changes without a full rebuild:

```bash
# Rebuild only cmdlog layers (uses cached apt layers)
make dev-rebuild-octobox

# Or manually:
CMDLOG_BUST=$(date +%s) docker compose -f octolab-hackvm/docker-compose.yml build octobox
```

## How Caching Works

The Dockerfile is structured for cache efficiency:

```dockerfile
# Heavy layers (cached) - ~5 minutes to build from scratch
RUN apt-get update && apt-get install -y xfce4 ...

# Cmdlog layers (at END of file) - ~5 seconds to rebuild
ARG CMDLOG_BUST=0
COPY rootfs/etc/profile.d/octolab-cmdlog.sh ...
RUN echo "cmdlog-bust=${CMDLOG_BUST}" > /etc/octolab-cmdlog.build-id
```

When you change `CMDLOG_BUST`, Docker only rebuilds from that `ARG` line onwards, preserving the cached apt layers.

## Troubleshooting

### "I see /etc/profile.d/octolog.sh in my container"

**Problem**: Container is running a stale image built from the legacy Dockerfile.

**Solution**:
```bash
# Force rebuild with cache bust
make dev-rebuild-octobox

# Or rebuild with no cache
docker compose -f octolab-hackvm/docker-compose.yml build --no-cache octobox
```

### "Build context is tiny (e.g., 135B)"

**Problem**: Compose is using the wrong build context.

**Solution**: Verify `docker-compose.yml` has:
```yaml
octobox:
  build:
    context: ../images/octobox-beta
```

Check with:
```bash
docker compose -f octolab-hackvm/docker-compose.yml config | grep -A5 "octobox:"
```

### "PROMPT_COMMAND doesn't include __octo_log_prompt"

**Problem**: Cmdlog script isn't being sourced in interactive shells.

**Diagnosis**:
```bash
# Check /etc/bash.bashrc sources octolab-cmdlog
docker exec <container> grep octolab-cmdlog /etc/bash.bashrc

# Check script exists and is readable
docker exec <container> ls -la /etc/octolab-cmdlog.sh /etc/profile.d/octolab-cmdlog.sh
```

**Solution**: Ensure the container was built from the correct Dockerfile (see above).

### "Commands aren't being logged to /evidence/tlog/"

**Problem**: Evidence directory may not be writable or LAB_ID not set.

**Diagnosis**:
```bash
# Check evidence dir permissions
docker exec <container> ls -la /evidence/

# Check LAB_ID
docker exec <container> bash -c 'echo LAB_ID=$LAB_ID'

# Check cmdlog debug output
docker exec <container> bash -ic 'OCTOLAB_CMDLOG_DEBUG=1 echo test'
```

## Files Reference

| File | Purpose |
|------|---------|
| `/etc/profile.d/octolab-cmdlog.sh` | Canonical cmdlog script (login shells) |
| `/etc/octolab-cmdlog.sh` | Shim that sources profile.d version |
| `/etc/bash.bashrc` | System bashrc, sources octolab-cmdlog.sh |
| `/etc/octolab-cmdlog.build-id` | Build marker (CMDLOG_BUST value) |
| `/etc/octolab-image.build-id` | Extended build marker (image, timestamp) |
| `/usr/local/bin/octolog-shell` | Shell wrapper using `script` command |

## Related Make Targets

| Target | Description |
|--------|-------------|
| `make dev-provenance` | Full provenance verification |
| `make dev-rebuild-octobox` | Rebuild with cmdlog cache bust |
| `make verify-cmdlog` | Quick cmdlog build test |
