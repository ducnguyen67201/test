> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Plan: Robust Command & Output Logging

## Overview

Replace the current `script`-based command logging with a more robust, tamper-resistant solution that captures both commands and their outputs accurately, with proper formatting and immediate write-to-disk.

## Requirements Analysis

1. **Very hard to tamper with**: Requires kernel-level or system-level logging that users cannot easily disable
2. **Accurate with proper formatting**: No weird newlines, clean output capture
3. **Written immediately OR hide export until FINISHED**: Either flush immediately or restrict evidence download to FINISHED labs only
4. **Human readable and easy to index**: Structured format (JSON preferred) for easy parsing and indexing

## Recommended Solution: **tlog** (Terminal I/O Logger)

**tlog** is a production-grade terminal session recorder developed by Red Hat, designed for security auditing and compliance.

### Why tlog?

- **Tamper-resistant**: Can run as a PAM module or systemd service, making it hard for users to bypass
- **Accurate output**: Captures terminal I/O at the TTY level, avoiding shell-specific quirks
- **Structured format**: Outputs JSON with clear separation of input/output/timing
- **Production-proven**: Used by Red Hat in enterprise environments
- **Immediate write**: Can be configured to flush immediately to disk
- **Human-readable**: JSON format is easy to parse, index, and read

### Alternative: **auditd** (Kernel-level, commands only)

**auditd** provides kernel-level command logging via `execve` system calls:
- **Extremely tamper-resistant**: Kernel-level, cannot be disabled by users
- **Limitation**: Only logs commands, NOT their outputs
- **Use case**: Can be used as a verification/backup layer alongside tlog

## Implementation Plan

### Phase 1: Install and Configure tlog

**Files to modify:**
- `octolab-hackvm/Dockerfile` - Install tlog package
- `octolab-hackvm/startup.sh` - Configure tlog to start with terminal sessions
- Create `octolab-hackvm/tlog.conf` - tlog configuration file

**Steps:**
1. Install `tlog` package in the OctoBox Dockerfile (Debian/Kali: `apt-get install tlog`)
2. Configure tlog to:
   - Log to `/evidence/commands.jsonl` (JSON Lines format, one entry per command/output)
   - Use immediate flush mode
   - Capture both input (commands) and output (stdout/stderr)
3. Configure PAM or systemd to automatically start tlog for the `pentester` user's terminal sessions
4. Test that commands and outputs are captured correctly

### Phase 2: Update Evidence Bundling

**Files to modify:**
- `backend/app/services/evidence_service.py` - Update to handle `commands.jsonl` instead of `commands.log`
- `backend/app/api/routes/labs.py` - Restrict evidence download to FINISHED status only

**Steps:**
1. Update `build_lab_network_evidence_tar` to look for `commands.jsonl` instead of `commands.log`
2. Update evidence endpoint to ONLY allow downloads when `lab.status == LabStatus.FINISHED`
3. Update metadata.json to reflect the new evidence format version

### Phase 3: Optional - Add auditd as Verification Layer

**Files to modify:**
- `octolab-hackvm/Dockerfile` - Install auditd
- Create `octolab-hackvm/audit.rules` - Audit rules for execve logging
- `backend/app/services/evidence_service.py` - Optionally bundle auditd logs

**Steps:**
1. Install `auditd` in OctoBox
2. Configure audit rules to log all `execve` system calls with key `command_exec`
3. Configure auditd to write logs to `/evidence/audit.log`
4. Update evidence bundling to include audit.log as a verification layer

### Phase 4: Testing & Documentation

**Files to create/modify:**
- `docs/evidence-collection.md` - Update with new logging approach
- Test script or manual test procedure

**Steps:**
1. Test that commands are logged immediately to `/evidence/commands.jsonl`
2. Test that outputs are captured accurately (no weird newlines)
3. Test that evidence download is blocked until lab is FINISHED
4. Test that evidence download works correctly after lab is FINISHED
5. Verify tamper-resistance: attempt to disable tlog from within OctoBox (should fail)
6. Update documentation

## Technical Details

### tlog Configuration

tlog can be configured via:
- **PAM module** (`pam_tlog`): Automatically starts tlog for login sessions
- **systemd service**: Runs tlog as a service
- **Direct invocation**: Called from shell wrapper (less tamper-resistant)

**Recommended**: Use PAM module for maximum tamper-resistance.

### tlog Output Format

tlog outputs JSON Lines format:
```json
{"ver":1,"rec":1,"time":"2025-11-21T14:00:00.123Z","in":"echo 'test'\n","out":"test\n"}
{"ver":1,"rec":2,"time":"2025-11-21T14:00:01.456Z","in":"ls -la\n","out":"total 72\n..."}
```

This format:
- Is human-readable
- Is easy to index (one JSON object per line)
- Separates input (commands) from output (results)
- Includes timestamps
- Can be parsed with standard JSON tools

### Evidence Download Restriction

Current code allows evidence download for `READY`, `FAILED`, or `FINISHED` labs. We should restrict to `FINISHED` only to ensure all commands are fully captured before export.

## Migration Path

1. **Keep existing `script` wrapper** as fallback during transition
2. **Deploy tlog** alongside script
3. **Test both** to ensure tlog works correctly
4. **Remove script wrapper** once tlog is verified
5. **Update evidence bundling** to use `commands.jsonl`

## Non-Goals

- Do NOT implement custom logging solutions (use proven tools)
- Do NOT try to parse shell history files (unreliable, easy to tamper)
- Do NOT use `PROMPT_COMMAND` or `trap DEBUG` (already proven unreliable)

## References

- tlog GitHub: https://github.com/Scribery/tlog
- tlog Documentation: https://github.com/Scribery/tlog/wiki
- auditd Documentation: https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/7/html/security_guide/chap-system_auditing

