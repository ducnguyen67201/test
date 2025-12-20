"""Subprocess utilities with security-first defaults.

All subprocess calls use shell=False and capture output.
Never log command arguments containing secrets.
"""

from __future__ import annotations

import subprocess
from typing import NamedTuple

from app.utils.redact import redact_argv


class CmdResult(NamedTuple):
    """Result from running a command."""

    returncode: int
    stdout: str
    stderr: str


def run_cmd(
    argv: list[str],
    *,
    timeout: float = 30.0,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> CmdResult:
    """
    Run a subprocess command with security-first defaults.

    Args:
        argv: Command and arguments as list (NO shell=True)
        timeout: Timeout in seconds
        check: If True, raise CalledProcessError on non-zero exit
        env: Environment variables (defaults to inheriting current env)

    Returns:
        CmdResult with returncode, stdout, stderr

    Raises:
        subprocess.CalledProcessError: If check=True and returncode != 0
        subprocess.TimeoutExpired: If command exceeds timeout

    SECURITY:
        - Always uses shell=False
        - Always captures output to prevent terminal leakage
    """
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        shell=False,  # SECURITY: Never use shell=True
        env=env,
    )

    return CmdResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def format_cmd_for_display(argv: list[str], *, redact: bool = True) -> str:
    """
    Format command for safe display/logging.

    Args:
        argv: Command arguments
        redact: If True, redact sensitive values

    Returns:
        Space-joined command string (redacted if requested)
    """
    if redact:
        argv = redact_argv(argv)
    return " ".join(argv)
