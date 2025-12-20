> **ARCHIVED**: This document is archived and may be outdated. For current documentation, see [docs/README.md](../README.md).

# Implement tlog Command Logging with Tamper-Resistance & noVNC Support

## Overview

Replace the current `script` wrapper with **tlog** (Terminal I/O Logger), a production-grade solution from Red Hat that captures both commands and their outputs in a tamper-resistant manner. Includes append-only file protection, integrity checks, and noVNC compatibility testing.

## Solution: tlog with Enhanced Tamper-Resistance

**Primary: tlog**
- Production-proven (Red Hat enterprise use)
- Tamper-resistant via PAM integration and append-only files
- Captures both commands AND outputs accurately
- JSON Lines format (human-readable, indexable)
- Can flush immediately to disk
- Works with noVNC (TTY-level capture)

**Tamper-Resistance Measures:**
1. **Append-only log files** (`chattr +a`) - Prevents modification/deletion, minimal performance impact
2. **File integrity checks** - SHA256 checksums in metadata to detect tampering
3. **Centralized logging** - Optional: Write to syslog/journal for additional protection
4. **Read-only evidence volume** - Mount evidence volume as read-only after lab termination

**Performance Impact:**
- `chattr +a`: Negligible overhead (native filesystem attribute)
- SHA256 hashing: ~500MB/s on modern CPUs (minimal for typical log sizes)
- **Encryption**: Would add 10-20% overhead, NOT recommended unless required
- **Recommendation**: Use append-only + checksums (best balance of security and performance)

**noVNC Compatibility:**
- tlog works with noVNC because it captures at the TTY level, not shell level
- Works regardless of how the terminal is spawned (interactive or non-interactive)
- Setting `tlog-rec-session` as the user's shell ensures all sessions are logged
- XFCE Terminal will use the configured shell, which is tlog

## Implementation Steps

### Phase 1: Install and Configure tlog with Tamper-Resistance

**Files to modify:**
- `octolab-hackvm/Dockerfile` - Install tlog and configure tamper-resistance
- `octolab-hackvm/startup.sh` - Configure tlog session recording
- Create `octolab-hackvm/tlog.conf` - tlog configuration

**Steps:**
1. In `Dockerfile`, add tlog installation:
   - Try: `apt-get install tlog` (if available in Kali repos)
   - If not available, build from source:
     ```dockerfile
     RUN apt-get install -y build-essential git libsystemd-dev && \
         git clone https://github.com/Scribery/tlog.git /tmp/tlog && \
         cd /tmp/tlog && \
         ./configure && make && make install
     ```

2. Configure tlog to log to `/evidence/commands.jsonl`:
   - Create `/etc/tlog/tlog-rec-session.conf` with:
     ```
     writer=file
     file-path=/evidence/commands.jsonl
     file-flush=yes
     ```

3. **Configure for noVNC compatibility:**
   - Since noVNC may spawn non-interactive shells, set `tlog-rec-session` as the user's shell directly:
     ```dockerfile
     RUN usermod -s /usr/bin/tlog-rec-session ${USERNAME}
     ```
   - This ensures tlog captures all terminal sessions, regardless of how they're spawned

4. **Implement tamper-resistance measures:**
   - In `Dockerfile`, after creating `/evidence` directory and before switching to user:
     ```dockerfile
     RUN touch /evidence/commands.jsonl && \
         chattr +a /evidence/commands.jsonl && \
         chmod 666 /evidence/commands.jsonl
     ```
   - Note: `chattr +a` must be run as root, and the file must exist first
   - The `+a` flag makes the file append-only (cannot be modified or deleted without root)

5. **Test noVNC compatibility:**
   - Verify tlog captures commands when opening terminal via noVNC
   - Test that XFCE Terminal sessions are logged correctly
   - Confirm JSON Lines format is correct

### Phase 2: Update Evidence Bundling with Integrity Checks

**Files to modify:**
- `backend/app/services/evidence_service.py` - Handle `commands.jsonl` and add integrity checks
- `backend/app/api/routes/labs.py` - Restrict evidence download to FINISHED labs only

**Steps:**
1. Update `build_lab_network_evidence_tar`:
   - Look for `commands.jsonl` instead of `commands.log`
   - Generate SHA256 checksum of `commands.jsonl` and include in metadata:
     ```python
     import hashlib
     # After reading commands.jsonl content
     checksum = hashlib.sha256(commands_content).hexdigest()
     metadata["commands_checksum"] = checksum
     metadata["commands_size"] = len(commands_content)
     ```
   - Update metadata to reflect new format version

2. **Add integrity verification:**
   - When bundling evidence, verify the log file hasn't been tampered with
   - Include checksum in metadata.json for client verification
   - Note: This doesn't prevent tampering, but detects it

3. Restrict evidence endpoint:
   - Change line 132 in `labs.py` from:
     ```python
     if lab.status not in (LabStatus.READY, LabStatus.FAILED, LabStatus.FINISHED):
     ```
     to:
     ```python
     if lab.status != LabStatus.FINISHED:
     ```
   - This ensures evidence is only available after lab is fully terminated

4. **Mount evidence volume as read-only after termination:**
   - In `ComposeLabRuntime.destroy_lab`, after stopping containers:
     - Document that evidence should be copied immediately after termination
     - Consider using `docker run` to remount volume as read-only (if possible)

### Phase 3: Fallback Implementation (if tlog fails or noVNC incompatible)

**If tlog installation/build fails on Kali OR if tlog doesn't work with noVNC:**

1. **Install auditd** in `Dockerfile`:
   ```dockerfile
   RUN apt-get install -y auditd
   ```

2. **Configure auditd** to log execve calls:
   - Create `/etc/audit/rules.d/command-logging.rules`:
     ```
     -a always,exit -F arch=b64 -S execve -k command_exec
     ```
   - Configure auditd to write to `/evidence/audit.log`

3. **Improve script wrapper** for better tamper-resistance:
   - Make log file append-only: `chattr +a /evidence/commands.log` (in Dockerfile as root)
   - Use `script -f` for immediate flush
   - Add integrity checks (optional: generate checksums periodically)

4. **Verify noVNC compatibility:**
   - Test that `script` command works correctly with XFCE Terminal via noVNC
   - Confirm commands and outputs are captured accurately

5. **Update evidence bundling** to include both:
   - `commands.log` (from script - outputs)
   - `audit.log` (from auditd - commands verification)
   - Include checksums for both files in metadata

### Phase 4: Testing & Documentation

**Files to create/modify:**
- `docs/evidence-collection.md` - Update with new approach
- Test procedure document

**Steps:**
1. Test tlog captures commands and outputs correctly via noVNC
2. Test JSON Lines format is human-readable and parseable
3. Test evidence download is blocked until FINISHED
4. Test tamper-resistance:
   - Attempt to delete `/evidence/commands.jsonl` (should fail with append-only)
   - Attempt to modify `/evidence/commands.jsonl` (should fail)
   - Verify checksums detect any tampering
5. Test performance: Verify append-only and checksums don't slow down logging
6. Update documentation

## Technical Details

### tlog Output Format

tlog outputs JSON Lines (one JSON object per line):
```json
{"ver":1,"rec":1,"time":"2025-11-21T14:00:00.123Z","in":"echo 'test'\n","out":"test\n"}
{"ver":1,"rec":2,"time":"2025-11-21T14:00:01.456Z","in":"ls -la\n","out":"total 72\n..."}
```

This format:
- Separates input (commands) from output (results)
- Includes timestamps
- Is easy to parse and index
- Is human-readable

### Tamper-Resistance Implementation

**Append-Only Files (`chattr +a`):**
- Prevents modification or deletion of log files
- Minimal performance impact (native filesystem feature)
- Requires root to remove the attribute
- Users cannot truncate or overwrite the file
- **Performance**: Negligible overhead

**Integrity Checks (SHA256 checksums):**
- Generated when bundling evidence
- Included in metadata.json
- Allows detection of tampering (doesn't prevent it)
- **Performance**: ~500MB/s on modern CPUs (minimal for typical log sizes)

**Encryption (NOT recommended):**
- Would add 10-20% overhead
- Not necessary if using append-only + checksums
- Only use if regulatory requirements demand it

### noVNC Compatibility

**tlog works with noVNC because:**
- tlog captures at the TTY level, not shell level
- Works regardless of how the terminal is spawned (interactive or non-interactive)
- Setting `tlog-rec-session` as the user's shell ensures all sessions are logged
- XFCE Terminal will use the configured shell, which is tlog

**Testing required:**
- Verify tlog captures commands from XFCE Terminal opened via noVNC
- Confirm output formatting is correct (no weird newlines)
- Test that multiple terminal windows are logged separately or together

### Evidence Download Restriction

Current code allows evidence for `READY`, `FAILED`, or `FINISHED`. We restrict to `FINISHED` only to ensure:
- All commands are fully captured
- Lab is completely terminated
- No partial evidence exports
- Evidence volume can be made read-only after termination

## Migration Path

1. Keep existing `script_wrapper.sh` as fallback during transition
2. Deploy tlog alongside (or replace) script wrapper
3. Test both to ensure tlog works correctly with noVNC
4. Remove script wrapper once tlog is verified
5. Update evidence bundling to use `commands.jsonl`

## Files to Modify

- `octolab-hackvm/Dockerfile` - Add tlog installation and append-only setup
- `octolab-hackvm/startup.sh` - Configure tlog
- `octolab-hackvm/tlog.conf` (new) - tlog configuration
- `backend/app/services/evidence_service.py` - Handle JSON Lines format and checksums
- `backend/app/api/routes/labs.py` - Restrict to FINISHED only
- `docs/evidence-collection.md` - Update documentation

## Non-Goals

- Do NOT implement encryption (performance overhead not worth it)
- Do NOT implement custom logging solutions
- Do NOT use shell history files (unreliable, easy to tamper)
- Do NOT use PROMPT_COMMAND/trap DEBUG (already proven unreliable)

