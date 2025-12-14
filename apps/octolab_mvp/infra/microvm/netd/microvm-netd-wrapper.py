#!/usr/bin/env python3
"""Wrapper script for microvm-netd.

This script is installed to /usr/local/bin/microvm-netd and provides
a stable entrypoint for both systemd and octolabctl.

The actual netd source path is baked in during installation.
This is the single source of truth for where netd lives.

SECURITY:
- Uses os.execv (no shell)
- Validates path exists before exec
- Path is baked in at install time, not from env
"""

import os
import sys

# This path is set during installation by octolabctl install
# DO NOT use environment variables - this is the source of truth
NETD_SOURCE_PATH = "__NETD_SOURCE_PATH__"


def main() -> int:
    """Execute the actual microvm-netd script."""
    # Validate source path - check if placeholder was replaced
    if "__NETD_SOURCE_PATH__" in NETD_SOURCE_PATH:
        print(
            "ERROR: microvm-netd wrapper not properly installed. "
            "Path placeholder not replaced.",
            file=sys.stderr,
        )
        return 1

    if not os.path.isfile(NETD_SOURCE_PATH):
        print(
            f"ERROR: microvm-netd source not found at: {NETD_SOURCE_PATH}",
            file=sys.stderr,
        )
        return 1

    # Build args: python3 <source> [original args...]
    exec_args = [sys.executable, NETD_SOURCE_PATH] + sys.argv[1:]

    # Replace this process with python3 running the actual netd
    # os.execv never returns on success
    try:
        os.execv(sys.executable, exec_args)
    except OSError as e:
        print(f"ERROR: Failed to exec microvm-netd: {e}", file=sys.stderr)
        return 1

    # Should never reach here
    return 1


if __name__ == "__main__":
    sys.exit(main())
