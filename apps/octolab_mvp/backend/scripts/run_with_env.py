#!/usr/bin/env python3
"""Secure environment file loader and command runner.

Loads environment variables from one or more .env files and runs a command
with the merged environment. Never uses shell=True, never sources files,
and redacts sensitive values in all output.

Usage:
    python backend/scripts/run_with_env.py --env backend/.env --env backend/.env.local -- command [args...]

Security:
    - shell=False always
    - No eval/exec of env file contents
    - Sensitive values are redacted in error output
    - Rejects shell syntax like `export FOO=bar` or command substitution
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Patterns for sensitive keys that should be redacted
SENSITIVE_PATTERNS = [
    re.compile(r".*PASSWORD.*", re.IGNORECASE),
    re.compile(r".*SECRET.*", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),
    re.compile(r".*_KEY_.*", re.IGNORECASE),
    re.compile(r"^DATABASE_URL$", re.IGNORECASE),
    re.compile(r".*TOKEN.*", re.IGNORECASE),
    re.compile(r".*CREDENTIAL.*", re.IGNORECASE),
]


def is_sensitive_key(key: str) -> bool:
    """Check if a key should have its value redacted."""
    return any(pattern.match(key) for pattern in SENSITIVE_PATTERNS)


def redact_value(key: str, value: str) -> str:
    """Redact sensitive values for safe logging."""
    if is_sensitive_key(key):
        if len(value) <= 4:
            return "****"
        return f"{value[:2]}...{value[-2:]}" if len(value) > 8 else "****"
    return value


def parse_env_line(line: str, line_num: int, filepath: Path) -> Optional[Tuple[str, str]]:
    """Parse a single line from an env file.

    Returns (key, value) tuple or None for blank/comment lines.
    Raises ValueError for invalid syntax.
    """
    # Strip whitespace
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith("#"):
        return None

    # Reject shell-style export syntax
    if line.startswith("export "):
        raise ValueError(
            f"{filepath}:{line_num}: Invalid syntax - 'export' prefix not allowed. "
            f"Use KEY=value format instead."
        )

    # Reject command substitution
    if "$(" in line or "`" in line:
        raise ValueError(
            f"{filepath}:{line_num}: Invalid syntax - command substitution not allowed."
        )

    # Must contain = and not start with =
    if "=" not in line:
        raise ValueError(
            f"{filepath}:{line_num}: Invalid syntax - line must be KEY=value format."
        )

    # Split on first =
    eq_pos = line.index("=")
    key = line[:eq_pos]
    value = line[eq_pos + 1:]

    # Validate key: must be alphanumeric + underscore, no spaces
    if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ValueError(
            f"{filepath}:{line_num}: Invalid key '{key}' - must be alphanumeric with underscores."
        )

    # Reject spaces around = (strict parsing)
    if key != key.strip():
        raise ValueError(
            f"{filepath}:{line_num}: Invalid syntax - no spaces allowed before '='."
        )

    # Strip quotes from value if present (both single and double)
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]

    return (key, value)


def load_env_file(filepath: Path) -> Dict[str, str]:
    """Load environment variables from a file.

    Returns dict of key=value pairs.
    Raises ValueError for syntax errors.
    """
    if not filepath.exists():
        return {}

    env = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            try:
                result = parse_env_line(line, line_num, filepath)
                if result:
                    key, value = result
                    env[key] = value
            except ValueError:
                raise

    return env


def merge_env_files(env_files: List[Path]) -> Dict[str, str]:
    """Load and merge multiple env files.

    Later files override earlier ones.
    """
    merged = {}
    for filepath in env_files:
        if filepath.exists():
            file_env = load_env_file(filepath)
            merged.update(file_env)
    return merged


def print_env_summary(env: Dict[str, str], label: str = "Environment") -> None:
    """Print environment summary with redacted values."""
    print(f"\n{label} ({len(env)} variables):", file=sys.stderr)
    for key in sorted(env.keys()):
        redacted = redact_value(key, env[key])
        print(f"  {key}={redacted}", file=sys.stderr)


def run_command(args: List[str], env: Dict[str, str]) -> int:
    """Run command with merged environment.

    Returns exit code.
    """
    # Merge with current environment (env vars override)
    full_env = os.environ.copy()
    full_env.update(env)

    try:
        result = subprocess.run(
            args,
            env=full_env,
            shell=False,  # SECURITY: Never use shell=True
            check=False,  # We handle return code ourselves
        )
        return result.returncode
    except FileNotFoundError:
        print(f"Error: Command not found: {args[0]}", file=sys.stderr)
        return 127
    except PermissionError:
        print(f"Error: Permission denied: {args[0]}", file=sys.stderr)
        return 126


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load env files and run a command.",
        usage="%(prog)s [--env FILE]... [--verbose] -- command [args...]",
    )
    parser.add_argument(
        "--env", "-e",
        action="append",
        dest="env_files",
        metavar="FILE",
        help="Env file to load (can be specified multiple times, later overrides earlier)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print loaded environment summary (with redacted secrets)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command and arguments to run (after --)",
    )

    args = parser.parse_args()

    # Handle command after --
    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        parser.error("No command specified. Usage: run_with_env.py --env .env -- command")

    # Default to backend/.env if no env files specified
    env_files = []
    if args.env_files:
        for f in args.env_files:
            env_files.append(Path(f))
    else:
        # Try to find default env files
        backend_env = Path("backend/.env")
        backend_local = Path("backend/.env.local")
        if backend_env.exists():
            env_files.append(backend_env)
        if backend_local.exists():
            env_files.append(backend_local)

    # Load and merge env files
    try:
        merged_env = merge_env_files(env_files)
    except ValueError as e:
        print(f"Error loading env file: {e}", file=sys.stderr)
        return 1

    # Print summary if verbose
    if args.verbose:
        loaded_files = [str(f) for f in env_files if f.exists()]
        print(f"Loaded env files: {', '.join(loaded_files) or '(none)'}", file=sys.stderr)
        print_env_summary(merged_env)
        print(f"\nRunning: {' '.join(command)}\n", file=sys.stderr)

    # Run command
    return run_command(command, merged_env)


if __name__ == "__main__":
    sys.exit(main())
