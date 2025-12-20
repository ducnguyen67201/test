#!/usr/bin/env python3
"""
OctoLab k3s Diagnostic Utility

Read-only diagnostic tool to identify k3s failures with secure redaction.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def redact_sensitive_data(text: str) -> str:
    """
    Redact sensitive patterns from text while preserving context.

    Redacts:
    - Authorization: Bearer tokens
    - token= / --token= values
    - kubeconfig cert/key base64 blocks
    - Base64-like blobs >40 chars
    """
    if not text:
        return text

    lines = text.split("\n")
    redacted_lines = []

    # Patterns for redaction
    bearer_pattern = re.compile(r"Authorization:\s*Bearer\s+(\S+)", re.IGNORECASE)
    token_pattern = re.compile(r"(token|--token)=([^\s]+)", re.IGNORECASE)
    token_colon_pattern = re.compile(r'["\']?token["\']?\s*:\s*["\']?([^"\'\s]+)', re.IGNORECASE)
    base64_pattern = re.compile(r"([A-Za-z0-9+/]{40,}={0,2})")
    cert_data_pattern = re.compile(
        r"(client-certificate-data|client-key-data|certificate-authority-data):\s*([A-Za-z0-9+/=]+)",
        re.IGNORECASE,
    )

    for line in lines:
        redacted_line = line

        # Redact Bearer tokens
        redacted_line = bearer_pattern.sub(r"Authorization: Bearer ***REDACTED_TOKEN***", redacted_line)

        # Redact token= values
        redacted_line = token_pattern.sub(r"\1=***REDACTED_TOKEN***", redacted_line)

        # Redact "token": "value" patterns
        redacted_line = token_colon_pattern.sub(r'token: "***REDACTED_TOKEN***"', redacted_line)

        # Redact cert/key data blocks
        redacted_line = cert_data_pattern.sub(
            r"\1: ***REDACTED_B64***", redacted_line
        )

        # Redact other base64-like blobs (but preserve short ones that might be IDs)
        def replace_base64(match):
            b64_str = match.group(1)
            # Don't redact if it looks like a short identifier
            if len(b64_str) < 40:
                return b64_str
            return "***REDACTED_B64***"

        redacted_line = base64_pattern.sub(replace_base64, redacted_line)

        redacted_lines.append(redacted_line)

    return "\n".join(redacted_lines)


def run_safe_command(
    cmd: list[str], timeout: int = 5, allow_sudo: bool = False
) -> dict[str, Any]:
    """
    Run command safely with timeout and best-effort semantics.

    Returns dict with returncode, stdout, stderr, cmd_used.
    Never raises exceptions.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "cmd_used": cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": 124,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "cmd_used": cmd,
        }
    except FileNotFoundError:
        # Command not found - try sudo fallback if allowed
        if allow_sudo and cmd[0] != "sudo":
            sudo_cmd = ["sudo"] + cmd
            try:
                result = subprocess.run(
                    sudo_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                return {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "cmd_used": sudo_cmd,
                }
            except Exception:
                pass
        return {
            "returncode": 127,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}",
            "cmd_used": cmd,
        }
    except Exception as e:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": str(e),
            "cmd_used": cmd,
        }


def get_cluster_info() -> dict[str, str]:
    """Get cluster information including context and type."""
    context = ""
    server_url = ""
    cluster_type = "unknown"
    error_msg = ""

    try:
        # Get current context
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            context = result.stdout.strip()

            # Get server URL for current context
            result = subprocess.run(
                ["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                server_url = result.stdout.strip()

                # Determine cluster type heuristically
                if context.startswith("k3d-") or "host.k3d.internal" in server_url or "0.0.0.0:" in server_url:
                    cluster_type = "k3d"
                elif server_url == "https://127.0.0.1:6443" and Path("/etc/rancher/k3s/k3s.yaml").exists():
                    cluster_type = "k3s-local"
                else:
                    cluster_type = "unknown"
    except subprocess.TimeoutExpired:
        error_msg = "kubectl command timed out"
    except Exception as e:
        error_msg = f"error getting cluster info: {type(e).__name__}"

    return {
        "context": context,
        "server_url": server_url if not error_msg else "",
        "cluster_type": cluster_type if not error_msg else "error",
        "error": error_msg
    }


def is_docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_wsl_mount_issues() -> dict[str, bool]:
    """Check for WSL mount issues that can cause k3s/kubelet to crash."""
    issue_found = False
    error_msg = ""

    try:
        if not os.path.exists("/proc/mounts"):
            return {"issue_found": False, "error": "/proc/mounts does not exist"}

        with open("/proc/mounts", "r") as f:
            mounts_content = f.read()

        # Check for Docker Desktop related problematic mounts
        for line in mounts_content.splitlines():
            if "C:\\\\Program Files\\\\Docker\\\\Docker\\\\resources\\\\ext\\\\" in line:
                return {"issue_found": True, "error": ""}

        # Check for overlay mounts that might conflict
        for line in mounts_content.splitlines():
            if "overlay" in line and "/mnt/wsl" in line:
                parts = line.split()
                if len(parts) > 3 and parts[2] == "overlay":
                    options = parts[3]
                    if "upperdir=" in options and "workdir=" in options and "lowerdir=" in options:
                        return {"issue_found": True, "error": ""}

        return {"issue_found": False, "error": ""}

    except Exception as e:
        return {"issue_found": False, "error": f"error checking mount issues: {type(e).__name__}"}


def check_kubectl_probes(verbose: bool) -> dict[str, Any]:
    """Check kubectl connectivity and API server readiness."""
    probes = {}
    method = "kubectl"

    # Also try to detect cluster type and context information
    cluster_info = get_cluster_info()

    # Try regular kubectl first
    kubectl_cmd = "kubectl"
    commands = [
        (["kubectl", "version", "--short"], "version"),
        (["kubectl", "get", "--raw=/readyz", "--request-timeout=5s"], "readyz"),
        (["kubectl", "get", "--raw=/livez", "--request-timeout=5s"], "livez"),
        (["kubectl", "get", "--raw=/healthz", "--request-timeout=5s"], "healthz"),
        (["kubectl", "get", "--raw=/openapi/v2", "--request-timeout=5s"], "openapi"),
        (["kubectl", "cluster-info"], "cluster_info"),
        (["kubectl", "get", "apiservices", "-o", "json"], "apiservices"),
    ]

    all_ok = True
    for cmd, name in commands:
        result = run_safe_command(cmd, timeout=5)
        probes[name] = {
            "ok": result["returncode"] == 0,
            "stdout": redact_sensitive_data(result["stdout"]),
            "stderr": redact_sensitive_data(result["stderr"]),
            "returncode": result["returncode"],
        }
        if result["returncode"] != 0:
            all_ok = False

    # Fallback to k3s kubectl if regular kubectl fails
    if not all_ok and Path("/usr/local/bin/k3s").exists():
        method = "k3s kubectl"
        k3s_commands = [
            (["sudo", "k3s", "kubectl", "version", "--short"], "version"),
            (["sudo", "k3s", "kubectl", "get", "--raw=/readyz", "--request-timeout=5s"], "readyz"),
            (["sudo", "k3s", "kubectl", "get", "--raw=/livez", "--request-timeout=5s"], "livez"),
            (["sudo", "k3s", "kubectl", "get", "--raw=/healthz", "--request-timeout=5s"], "healthz"),
            (["sudo", "k3s", "kubectl", "get", "--raw=/openapi/v2", "--request-timeout=5s"], "openapi"),
            (["sudo", "k3s", "kubectl", "cluster-info"], "cluster_info"),
            (["sudo", "k3s", "kubectl", "get", "apiservices", "-o", "json"], "apiservices"),
        ]

        all_ok = True
        for cmd, name in k3s_commands:
            result = run_safe_command(cmd, timeout=5)
            probes[name] = {
                "ok": result["returncode"] == 0,
                "stdout": redact_sensitive_data(result["stdout"]),
                "stderr": redact_sensitive_data(result["stderr"]),
                "returncode": result["returncode"],
            }
            if result["returncode"] != 0:
                all_ok = False

    return {"probes": probes, "method": method, "all_ok": all_ok}


def check_systemd_status() -> dict[str, Any]:
    """Check k3s systemd service status."""
    is_active_result = run_safe_command(["systemctl", "is-active", "k3s"], timeout=5)
    status_result = run_safe_command(
        ["systemctl", "status", "k3s", "--no-pager"], timeout=5
    )

    return {
        "is_active": is_active_result["stdout"].strip() if is_active_result["returncode"] == 0 else "unknown",
        "status_output": redact_sensitive_data(status_result["stdout"]),
        "status_stderr": redact_sensitive_data(status_result["stderr"]),
    }


def check_k3s_journal(verbose: bool) -> dict[str, Any]:
    """Check k3s journal logs with bounded output."""
    n_lines = 500 if verbose else 300

    boot_logs_result = run_safe_command(
        ["journalctl", "-u", "k3s", "-b", "--no-pager", "-n", str(n_lines)],
        timeout=10,
        allow_sudo=True,
    )

    recent_logs_result = run_safe_command(
        [
            "journalctl",
            "-u",
            "k3s",
            "--since",
            "30 min ago",
            "--no-pager",
            "-n",
            str(n_lines),
        ],
        timeout=10,
        allow_sudo=True,
    )

    return {
        "boot_logs": redact_sensitive_data(boot_logs_result["stdout"]),
        "recent_logs": redact_sensitive_data(recent_logs_result["stdout"]),
        "boot_stderr": redact_sensitive_data(boot_logs_result["stderr"]),
        "recent_stderr": redact_sensitive_data(recent_logs_result["stderr"]),
    }


def check_host_environment() -> dict[str, Any]:
    """Check host environment (disk, ports, time, kernel)."""
    disk_result = run_safe_command(["df", "-h"], timeout=5)
    inode_result = run_safe_command(["df", "-i"], timeout=5)
    ports_result = run_safe_command(["ss", "-ltnp"], timeout=5, allow_sudo=True)
    time_result = run_safe_command(["date"], timeout=5)
    dmesg_result = run_safe_command(
        ["dmesg", "-T"], timeout=5, allow_sudo=True
    )

    # Limit dmesg output
    dmesg_output = dmesg_result["stdout"]
    if dmesg_output:
        dmesg_lines = dmesg_output.split("\n")
        dmesg_output = "\n".join(dmesg_lines[-120:])

    return {
        "disk_space": disk_result["stdout"],
        "inodes": inode_result["stdout"],
        "ports": redact_sensitive_data(ports_result["stdout"]),
        "time": time_result["stdout"].strip(),
        "kernel_errors": redact_sensitive_data(dmesg_output),
    }


def analyze_apiservices(apiservices_json: str) -> list[dict[str, str]]:
    """
    Analyze APIServices status from kubectl get apiservices -o json.
    Returns list of failing APIServices with name, status, and reason.
    """
    failing_services = []
    try:
        import json
        data = json.loads(apiservices_json)
        for item in data.get("items", []):
            name = item.get("metadata", {}).get("name", "unknown")
            conditions = item.get("status", {}).get("conditions", [])

            # Look for conditions that indicate failure
            for condition in conditions:
                status = condition.get("status", "Unknown")
                reason = condition.get("reason", "Unknown")
                message = condition.get("message", "")

                # If any condition indicates failure, add to failing list
                if (reason.lower() in ["failed", "connection_failed", "service_not_available"] or
                    (status == "False" and reason not in ["Orphaned", "Removed"])):  # Orphaned/Removed may be intentional
                    failing_services.append({
                        "name": name,
                        "reason": reason,
                        "message": message[:200] if message else ""  # Truncate long messages
                    })
    except Exception:
        # If we can't parse JSON, return an empty list
        pass

    return failing_services


def diagnose_root_cause(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    Diagnose root cause using heuristics.

    Returns dict with diagnosis, confidence, evidence_lines, next_actions.
    """
    systemd_status = evidence.get("systemd_status", {})
    journal_logs = evidence.get("journal_logs", {})
    kubectl_probes = evidence.get("kubectl_probes", {})
    host_env = evidence.get("host_env", {})

    is_active = systemd_status.get("is_active", "")
    boot_logs = journal_logs.get("boot_logs", "")
    recent_logs = journal_logs.get("recent_logs", "")
    all_logs = boot_logs + "\n" + recent_logs

    probes = kubectl_probes.get("probes", {})
    readyz_ok = probes.get("readyz", {}).get("ok", False)
    livez_ok = probes.get("livez", {}).get("ok", False)
    healthz_ok = probes.get("healthz", {}).get("ok", False)
    apiservices_ok = probes.get("apiservices", {}).get("ok", False)

    # Get failing APIServices if the call was successful
    failing_apiservices = []
    if apiservices_ok and probes.get("apiservices", {}).get("stdout"):
        failing_apiservices = analyze_apiservices(probes["apiservices"]["stdout"])

    # Distinguish between different states
    # State 1: k3s service is down
    if is_active not in ["active", "activating"]:
        evidence_lines = []
        if "connection refused" in all_logs.lower():
            for line in all_logs.split("\n"):
                if "connection refused" in line.lower():
                    evidence_lines.append(line.strip())
                    if len(evidence_lines) >= 5:
                        break

        return {
            "diagnosis": "k3s_service_down",
            "confidence": "high",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Start k3s: sudo systemctl start k3s",
                "Check status: sudo systemctl status k3s",
                "Check logs: sudo journalctl -u k3s -n 50",
            ],
        }

    # State 2: k3s service is up but apiserver not ready
    if is_active == "active" and not readyz_ok:
        # Check if it's a general unavailability (apiserver issues) vs specific failures
        if not livez_ok or not healthz_ok:
            # Both are down - likely apiserver issues
            evidence_lines = []
            for line in all_logs.split("\n"):
                if any(keyword in line.lower() for keyword in ["unavailable", "timeout", "connection refused"]):
                    evidence_lines.append(line.strip())
                    if len(evidence_lines) >= 5:
                        break

            # Check for specific aggregated API failures
            if failing_apiservices:
                # Add info about failing APIs to diagnosis
                for svc in failing_apiservices:
                    evidence_lines.append(f"APIService {svc['name']} failed: {svc['reason']}")

            return {
                "diagnosis": "apiserver_not_ready",
                "confidence": "high",
                "evidence_lines": evidence_lines[:15],  # More space for API info
                "next_actions": [
                    "Check status: sudo systemctl status k3s",
                    f"Found {len(failing_apiservices)} failing APIServices - see details above",
                    "Check full logs: sudo journalctl -u k3s -n 100",
                    "Restart k3s if needed: sudo systemctl restart k3s",
                ],
            }
        else:
            # readyz alone is failing - possibly just not ready yet
            return {
                "diagnosis": "apiserver_not_ready",
                "confidence": "medium",
                "evidence_lines": ["API server readyz check failed, but livez/healthz okay - may be temporary"],
                "next_actions": [
                    "Wait a moment and retry",
                    "Check status: sudo systemctl status k3s",
                    "Check logs: sudo journalctl -u k3s -n 50",
                ],
            }

    # Heuristic 1: port conflict (check before general "not running")
    if "address already in use" in all_logs.lower() or "bind: address already in use" in all_logs.lower():
        evidence_lines = []
        for line in all_logs.split("\n"):
            if "address already in use" in line.lower() or "bind:" in line.lower():
                evidence_lines.append(line.strip())
                if len(evidence_lines) >= 5:
                    break

        ports_info = host_env.get("ports", "")
        return {
            "diagnosis": "port_conflict",
            "confidence": "high",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check what's using ports: sudo ss -ltnp | grep -E '6443|2379|2380'",
                "Stop conflicting service or restart k3s: sudo systemctl restart k3s",
                "Check k3s logs: sudo journalctl -u k3s -n 50",
            ],
        }

    # Heuristic 2: general k3s not running (fallback if systemd check was inconclusive)
    if not readyz_ok and not livez_ok and not healthz_ok:
        evidence_lines = []
        if "connection refused" in all_logs.lower():
            for line in all_logs.split("\n"):
                if "connection refused" in line.lower():
                    evidence_lines.append(line.strip())
                    if len(evidence_lines) >= 5:
                        break

        return {
            "diagnosis": "k3s_not_running",
            "confidence": "high",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check k3s status: sudo systemctl status k3s",
                "Start k3s: sudo systemctl start k3s",
                "Check logs: sudo journalctl -u k3s -n 50",
            ],
        }

    # Heuristic 3: disk full / inode exhaustion
    disk_space = host_env.get("disk_space", "")
    inodes = host_env.get("inodes", "")
    if "no space left" in all_logs.lower() or "enospc" in all_logs.lower():
        evidence_lines = []
        for line in all_logs.split("\n"):
            if "no space left" in line.lower() or "enospc" in line.lower():
                evidence_lines.append(line.strip())
                if len(evidence_lines) >= 5:
                    break

        return {
            "diagnosis": "disk_full",
            "confidence": "high",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check disk space: df -h",
                "Check inodes: df -i",
                "Clean up k3s data: sudo du -sh /var/lib/rancher/k3s",
                "Free space or expand disk",
            ],
        }

    # Check for 100% disk/inode usage
    if disk_space:
        for line in disk_space.split("\n"):
            if "/var/lib/rancher/k3s" in line or "/var/lib/rancher" in line:
                parts = line.split()
                if len(parts) >= 5:
                    usage = parts[4].rstrip("%")
                    try:
                        if int(usage) >= 95:
                            return {
                                "diagnosis": "disk_full",
                                "confidence": "high",
                                "evidence_lines": [line],
                                "next_actions": [
                                    "Disk usage is high. Check: df -h",
                                    "Check inodes: df -i",
                                    "Clean up k3s data if needed",
                                ],
                            }
                    except ValueError:
                        pass

    # Heuristic 4: cert expired / clock skew
    if (
        "certificate" in all_logs.lower()
        and ("expired" in all_logs.lower() or "not yet valid" in all_logs.lower() or "clock skew" in all_logs.lower())
    ):
        evidence_lines = []
        for line in all_logs.split("\n"):
            if "certificate" in line.lower() and (
                "expired" in line.lower() or "not yet valid" in line.lower() or "clock skew" in line.lower()
            ):
                evidence_lines.append(line.strip())
                if len(evidence_lines) >= 5:
                    break

        return {
            "diagnosis": "cert_clock_issue",
            "confidence": "medium",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check system time: date",
                "Sync time: sudo timedatectl set-ntp true",
                "Check k3s certs: sudo ls -la /var/lib/rancher/k3s/server/tls",
                "Restart k3s: sudo systemctl restart k3s",
            ],
        }

    # Heuristic 5: sqlite datastore issue
    if "sqlite" in all_logs.lower() and (
        "corrupt" in all_logs.lower() or "locked" in all_logs.lower() or "database is locked" in all_logs.lower()
    ):
        evidence_lines = []
        for line in all_logs.split("\n"):
            if "sqlite" in line.lower() and (
                "corrupt" in line.lower() or "locked" in line.lower()
            ):
                evidence_lines.append(line.strip())
                if len(evidence_lines) >= 5:
                    break

        return {
            "diagnosis": "datastore_issue",
            "confidence": "high",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check k3s datastore: sudo ls -la /var/lib/rancher/k3s/server/db",
                "Backup and check SQLite: sudo sqlite3 /var/lib/rancher/k3s/server/db/state.db '.tables'",
                "If corrupted, may need to reset k3s (destructive): backup first!",
            ],
        }

    # Heuristic 7: cgroup / networking issue
    if (
        ("iptables" in all_logs.lower() or "nftables" in all_logs.lower() or "cgroup" in all_logs.lower())
        and ("error" in all_logs.lower() or "failed" in all_logs.lower() or "permission denied" in all_logs.lower())
    ):
        evidence_lines = []
        for line in all_logs.split("\n"):
            if ("iptables" in line.lower() or "nftables" in line.lower() or "cgroup" in line.lower()) and (
                "error" in line.lower() or "failed" in line.lower()
            ):
                evidence_lines.append(line.strip())
                if len(evidence_lines) >= 5:
                    break

        return {
            "diagnosis": "networking_issue",
            "confidence": "medium",
            "evidence_lines": evidence_lines[:10],
            "next_actions": [
                "Check iptables: sudo iptables -L",
                "Check cgroup: mount | grep cgroup",
                "Check kernel modules: lsmod | grep -E 'iptable|nf_conntrack'",
                "Restart k3s: sudo systemctl restart k3s",
            ],
        }

    # Heuristic 8: unknown - extract top error patterns
    error_lines = []
    for line in all_logs.split("\n"):
        line_lower = line.lower()
        if any(
            keyword in line_lower
            for keyword in ["error", "failed", "fatal", "panic", "crash"]
        ):
            error_lines.append(line.strip())

    # Count common error patterns
    error_patterns = {}
    for line in error_lines:
        for pattern in ["connection refused", "timeout", "permission denied", "no such file"]:
            if pattern in line.lower():
                error_patterns[pattern] = error_patterns.get(pattern, 0) + 1

    top_errors = sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "diagnosis": "unknown",
        "confidence": "low",
        "evidence_lines": error_lines[:10],
        "next_actions": [
            "Review full logs: sudo journalctl -u k3s -n 100",
            "Check k3s status: sudo systemctl status k3s",
            "Check system resources: df -h && free -h",
            "Check for recent errors in logs above",
        ],
    }


def print_diagnosis(evidence: dict[str, Any], diagnosis: dict[str, Any], verbose: bool) -> None:
    """Print formatted diagnosis output."""
    print("=== OctoLab k3s Doctor ===\n")

    # Diagnosis section
    print("[DIAGNOSIS]")
    print(f"Status: {diagnosis['diagnosis']}")
    print(f"Confidence: {diagnosis['confidence']}\n")

    # Evidence section
    if diagnosis["evidence_lines"]:
        print("[EVIDENCE]")
        for line in diagnosis["evidence_lines"]:
            print(f"  {line}")
        print()

    # Kubectl probes
    kubectl_probes = evidence.get("kubectl_probes", {})
    probes = kubectl_probes.get("probes", {})
    method = kubectl_probes.get("method", "unknown")

    print("[KUBECTL PROBES]")
    print(f"readyz: {'OK' if probes.get('readyz', {}).get('ok') else 'FAILED'}")
    print(f"livez: {'OK' if probes.get('livez', {}).get('ok') else 'FAILED'}")
    print(f"healthz: {'OK' if probes.get('healthz', {}).get('ok') else 'FAILED'}")
    print(f"openapi: {'OK' if probes.get('openapi', {}).get('ok') else 'FAILED'}")
    print(f"cluster-info: {'OK' if probes.get('cluster_info', {}).get('ok') else 'FAILED'}")
    print(f"APIServices: {'OK' if probes.get('apiservices', {}).get('ok') else 'FAILED'}")
    print(f"Method used: {method}\n")

    # Add cluster context information
    cluster_info = get_cluster_info()
    print("[CLUSTER CONTEXT]")
    print(f"Current Context: {cluster_info['context'] or 'N/A'}")
    print(f"Server URL: {cluster_info['server_url'] or 'N/A'}")
    print(f"Detected Type: {cluster_info['cluster_type']}\n")

    # Check for WSL mount issues
    mount_check = check_wsl_mount_issues()
    if mount_check.get('issue_found', False):
        print("[WSL MOUNT ISSUE DETECTED]")
        print("WARNING: Docker Desktop WSL integration detected that may cause k3s/kubelet crashes.")
        print("This typically happens when k3s runs inside WSL with Docker Desktop mounted paths.")
        print("Recommendation: Use k3d (k3s-in-Docker) instead of k3s directly in WSL.\n")
    elif not mount_check.get('error'):
        print("[WSL MOUNT STATUS]")
        print("No problematic Docker Desktop mounts detected for k3s.\n")

    # Check for failing APIServices and display if present
    if probes.get('apiservices', {}).get('ok') and probes.get('apiservices', {}).get('stdout'):
        failing_apiservices = analyze_apiservices(probes['apiservices']['stdout'])
        if failing_apiservices:
            print(f"[APISERVICES - {len(failing_apiservices)} failing]")
            for svc in failing_apiservices:
                print(f"  {svc['name']}: {svc['reason']}")
                if svc.get('message'):
                    print(f"    {svc['message']}")
            print()

    # Systemd status
    systemd_status = evidence.get("systemd_status", {})
    print("[SYSTEMD STATUS]")
    print(f"Service: {systemd_status.get('is_active', 'unknown')}\n")

    # Host checks
    host_env = evidence.get("host_env", {})
    print("[HOST CHECKS]")
    disk_space = host_env.get("disk_space", "")
    if disk_space:
        # Extract relevant line for k3s
        for line in disk_space.split("\n"):
            if "/var/lib/rancher" in line or "Filesystem" in line:
                print(f"Disk: {line}")
                break
    else:
        print("Disk: (check failed)")

    ports = host_env.get("ports", "")
    if ports:
        port_6443 = "not found"
        for line in ports.split("\n"):
            if ":6443" in line:
                port_6443 = line.strip()
                break
        print(f"Port 6443: {port_6443}")
    else:
        print("Ports: (check failed)")

    print(f"Time: {host_env.get('time', 'unknown')}\n")

    # Next actions
    print("[NEXT ACTIONS]")
    for i, action in enumerate(diagnosis["next_actions"], 1):
        print(f"{i}. {action}")

    # Add k3d quickstart if Docker is available and not already using k3d
    cluster_info = get_cluster_info()
    if is_docker_available() and cluster_info.get('cluster_type') != 'k3d':
        print(f"\n[K3D QUICKSTART]")
        print("k3d (k3s in Docker) provides a stable local Kubernetes cluster for development:")
        print("1. Create a k3d cluster: k3d cluster create octolab-dev --api-port 6550")
        print("2. Verify: kubectl config current-context (should show k3d-octolab-dev)")
        print("3. Test: kubectl get nodes (should show k3d cluster nodes)")
        print("4. Now the K8s runtime will connect to this k3d cluster")

    if verbose:
        print("\n[VERBOSE OUTPUT]")
        print("\n--- Full Journal Logs (Boot) ---")
        journal_logs = evidence.get("journal_logs", {})
        boot_logs = journal_logs.get("boot_logs", "")
        if boot_logs:
            print(boot_logs[-2000:])  # Last 2000 chars
        else:
            print("(no logs available)")


def run_selftest() -> bool:
    """Run self-test for redaction and heuristics."""
    print("Running self-tests...\n")

    # Test 1: Redaction
    test_text = """
Authorization: Bearer abc123def456ghi789
token=secret-token-value
"token": "another-secret"
client-certificate-data: LS0tLS1CRUdJTi...
Some base64 data: ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890+/==
Error: connection refused
"""
    redacted = redact_sensitive_data(test_text)
    if "abc123def456ghi789" in redacted or "secret-token-value" in redacted:
        print("FAIL: Redaction test failed - tokens not redacted")
        return False
    if "***REDACTED_TOKEN***" not in redacted:
        print("FAIL: Redaction test failed - no redaction markers")
        return False
    print("PASS: Redaction test")

    # Test 2: Diagnosis heuristics - k3s_service_down should be detected when is_active is not 'active'
    mock_evidence = {
        "systemd_status": {"is_active": "failed"},
        "journal_logs": {
            "boot_logs": "FATA[2024] failed to start: address already in use",
            "recent_logs": "",
        },
        "kubectl_probes": {"probes": {"readyz": {"ok": False}}},
        "host_env": {},
    }
    diagnosis = diagnose_root_cause(mock_evidence)
    if diagnosis["diagnosis"] not in ["k3s_service_down", "k3s_not_running"]:
        print(f"FAIL: Diagnosis test failed - expected 'k3s_service_down' or 'k3s_not_running', got '{diagnosis['diagnosis']}'")
        return False
    print("PASS: Diagnosis heuristics test")

    print("\nAll self-tests passed!")
    return True


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="OctoLab k3s diagnostic utility"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show verbose output"
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON output (not yet implemented)"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="Run self-tests and exit"
    )

    args = parser.parse_args()

    if args.json:
        print("JSON output not yet implemented", file=sys.stderr)
        sys.exit(1)

    if args.selftest:
        success = run_selftest()
        sys.exit(0 if success else 1)

    # Gather evidence
    print("Gathering diagnostic information...\n")
    kubectl_probes = check_kubectl_probes(args.verbose)
    systemd_status = check_systemd_status()
    journal_logs = check_k3s_journal(args.verbose)
    host_env = check_host_environment()

    evidence = {
        "kubectl_probes": kubectl_probes,
        "systemd_status": systemd_status,
        "journal_logs": journal_logs,
        "host_env": host_env,
    }

    # Diagnose
    diagnosis = diagnose_root_cause(evidence)

    # Print output
    print_diagnosis(evidence, diagnosis, args.verbose)

    # Determine exit code
    if diagnosis["diagnosis"] == "k3s_not_running":
        sys.exit(2)
    elif kubectl_probes.get("all_ok") and systemd_status.get("is_active") == "active":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

