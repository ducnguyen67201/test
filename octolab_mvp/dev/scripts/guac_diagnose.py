#!/usr/bin/env python3
"""Guacamole DB diagnosis helper.

Classifies common failure modes based on container logs and inspect output.
Used by guac_up.sh for actionable error messages.

Security:
- Redacts sensitive values matching: *PASS*, *PASSWORD*, *SECRET*, *TOKEN*, *KEY*
- Never prints full environment dumps
"""

import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DiagnosisCode(str, Enum):
    """Diagnosis codes for Guac DB failures."""

    PORT_BIND_CONFLICT = "PORT_BIND_CONFLICT"
    STALE_VOLUME_CREDS = "STALE_VOLUME_CREDS"
    INIT_SQL_ERROR = "INIT_SQL_ERROR"
    HEALTHCHECK_ENV_NOT_EXPANDED = "HEALTHCHECK_ENV_NOT_EXPANDED"
    DB_FILES_INCOMPATIBLE = "DB_FILES_INCOMPATIBLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNKNOWN = "UNKNOWN"


@dataclass
class Diagnosis:
    """A diagnosis result with code, message, and remediation."""

    code: DiagnosisCode
    summary: str
    detail: Optional[str] = None
    remediation: Optional[str] = None


# Patterns for sensitive keys to redact
# Note: Using [^\n]* instead of .* to prevent matching across lines
SENSITIVE_PATTERNS = [
    re.compile(r"([^\n]*(?:PASS|PASSWORD|SECRET|TOKEN|KEY)[^\n=]*)=([^\n]+)", re.IGNORECASE),
    re.compile(r"(password)\s*[:=]\s*(\S+)", re.IGNORECASE),
]


def redact_sensitive(text: str) -> str:
    """Redact sensitive values from text.

    Args:
        text: Text that may contain sensitive values

    Returns:
        Text with sensitive values replaced with ****
    """
    result = text
    for pattern in SENSITIVE_PATTERNS:
        result = pattern.sub(r"\1=****", result)
    return result


def classify_logs(log_text: str) -> list[Diagnosis]:
    """Classify failure mode from container logs.

    Args:
        log_text: Docker container logs

    Returns:
        List of Diagnosis objects (may be empty if no issues detected)
    """
    diagnoses = []

    # Port bind conflict
    if re.search(r"address already in use|port is already allocated|bind.*failed", log_text, re.IGNORECASE):
        diagnoses.append(Diagnosis(
            code=DiagnosisCode.PORT_BIND_CONFLICT,
            summary="Port bind conflict detected",
            detail="Another process is using the required port",
            remediation="Check for other PostgreSQL instances: lsof -i :5432"
        ))

    # Stale volume with different credentials
    cred_patterns = [
        r"password authentication failed",
        r"role.*does not exist",
        r"FATAL:.*authentication failed",
        r"no pg_hba\.conf entry",
    ]
    for pattern in cred_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            diagnoses.append(Diagnosis(
                code=DiagnosisCode.STALE_VOLUME_CREDS,
                summary="Database credential mismatch",
                detail="Volume contains data from a different user/password configuration",
                remediation="Run: make guac-reset-db"
            ))
            break

    # Database files incompatible (version mismatch)
    if re.search(r"database files are incompatible|was created by PostgreSQL version", log_text, re.IGNORECASE):
        diagnoses.append(Diagnosis(
            code=DiagnosisCode.DB_FILES_INCOMPATIBLE,
            summary="PostgreSQL version mismatch",
            detail="Volume data was created with a different PostgreSQL version",
            remediation="Run: make guac-reset-db (will delete data)"
        ))

    # Init SQL errors
    sql_error_match = re.search(r"(ERROR:.*?(?:syntax error|relation.*already exists|type.*already exists).*?)(?:\n|$)", log_text, re.IGNORECASE)
    if sql_error_match:
        # Extract first SQL error line (redacted)
        error_line = redact_sensitive(sql_error_match.group(1)[:200])
        diagnoses.append(Diagnosis(
            code=DiagnosisCode.INIT_SQL_ERROR,
            summary="Init SQL script error",
            detail=f"First error: {error_line}",
            remediation="Check infra/guacamole/init/initdb.sql syntax"
        ))

    # Permission denied on data directory
    if re.search(r"permission denied|could not open file.*Permission denied|mkdir.*Permission denied", log_text, re.IGNORECASE):
        diagnoses.append(Diagnosis(
            code=DiagnosisCode.PERMISSION_DENIED,
            summary="Permission denied on data directory",
            detail="Container cannot write to volume",
            remediation="Check volume permissions or run: make guac-reset-db"
        ))

    return diagnoses


def classify_inspect(inspect_text: str) -> list[Diagnosis]:
    """Classify failure mode from docker inspect output.

    Args:
        inspect_text: Output from docker inspect (Health section)

    Returns:
        List of Diagnosis objects
    """
    diagnoses = []

    # Healthcheck command shows literal $POSTGRES_USER (not expanded)
    if re.search(r'\$POSTGRES_USER|\$\{POSTGRES_USER\}', inspect_text):
        if "pg_isready" in inspect_text.lower():
            diagnoses.append(Diagnosis(
                code=DiagnosisCode.HEALTHCHECK_ENV_NOT_EXPANDED,
                summary="Healthcheck environment variables not expanding",
                detail="Healthcheck command contains literal $POSTGRES_USER instead of expanded value",
                remediation="Ensure healthcheck uses CMD-SHELL format with proper escaping"
            ))

    return diagnoses


def classify(log_text: str, inspect_text: str) -> list[Diagnosis]:
    """Classify failure mode from logs and inspect output.

    Args:
        log_text: Docker container logs
        inspect_text: Output from docker inspect

    Returns:
        List of Diagnosis objects. If empty, issue is UNKNOWN.
    """
    diagnoses = []
    diagnoses.extend(classify_logs(log_text))
    diagnoses.extend(classify_inspect(inspect_text))

    # Deduplicate by code
    seen_codes = set()
    unique_diagnoses = []
    for d in diagnoses:
        if d.code not in seen_codes:
            seen_codes.add(d.code)
            unique_diagnoses.append(d)

    return unique_diagnoses


def format_diagnoses(diagnoses: list[Diagnosis]) -> str:
    """Format diagnoses for human-readable output.

    Args:
        diagnoses: List of Diagnosis objects

    Returns:
        Formatted string for terminal output
    """
    if not diagnoses:
        return "No specific issue detected. Check logs manually."

    lines = []
    for i, d in enumerate(diagnoses, 1):
        lines.append(f"\n[Issue {i}] {d.summary}")
        if d.detail:
            lines.append(f"  Detail: {d.detail}")
        if d.remediation:
            lines.append(f"  Fix: {d.remediation}")

    return "\n".join(lines)


def main():
    """CLI interface for testing.

    Usage:
        echo "log text" | python guac_diagnose.py --logs
        echo "inspect text" | python guac_diagnose.py --inspect
        python guac_diagnose.py --logs --inspect < combined.txt
    """
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose Guac DB issues")
    parser.add_argument("--logs", type=str, default="", help="Log text to analyze")
    parser.add_argument("--inspect", type=str, default="", help="Inspect text to analyze")
    parser.add_argument("--stdin", action="store_true", help="Read from stdin")

    args = parser.parse_args()

    log_text = args.logs
    inspect_text = args.inspect

    if args.stdin:
        log_text = sys.stdin.read()

    diagnoses = classify(log_text, inspect_text)
    print(format_diagnoses(diagnoses))

    # Exit 0 if no issues found, 1 if issues detected
    sys.exit(0 if not diagnoses else 1)


if __name__ == "__main__":
    main()
