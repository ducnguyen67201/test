#!/usr/bin/env python3
"""Ensure backend/.env.local exists with required secrets.

Creates the file if missing and generates stable secrets (like GUAC_ENC_KEY)
that must not change once set. Existing values are never overwritten.

Usage:
    python dev/scripts/ensure_env_local.py [--repo-root PATH]

Security:
    - Sets file permissions to 600 (owner read/write only)
    - Never prints actual secret values
    - Never overwrites existing secrets
"""

import argparse
import base64
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Patterns for sensitive keys that should be redacted in output
SENSITIVE_PATTERNS = [
    re.compile(r".*PASSWORD.*", re.IGNORECASE),
    re.compile(r".*SECRET.*", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),
    re.compile(r".*_KEY_.*", re.IGNORECASE),
    re.compile(r"^DATABASE_URL$", re.IGNORECASE),
]


def is_sensitive_key(key: str) -> bool:
    """Check if a key should have its value redacted."""
    return any(pattern.match(key) for pattern in SENSITIVE_PATTERNS)


def redact_value(key: str, value: str) -> str:
    """Redact sensitive values for safe output."""
    if is_sensitive_key(key):
        return "****"
    return value


def generate_fernet_key() -> str:
    """Generate a Fernet-compatible encryption key.

    Tries to use cryptography library if available,
    falls back to manual generation otherwise.
    """
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    except ImportError:
        # Fallback: generate 32-byte URL-safe base64 key
        # This is compatible with Fernet
        key_bytes = secrets.token_bytes(32)
        return base64.urlsafe_b64encode(key_bytes).decode()


def parse_env_file(filepath: Path) -> Dict[str, str]:
    """Parse an env file into a dict.

    Simple KEY=value parser that ignores comments and blank lines.
    """
    if not filepath.exists():
        return {}

    env = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            eq_pos = line.index("=")
            key = line[:eq_pos].strip()
            value = line[eq_pos + 1:].strip()
            # Strip quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key:
                env[key] = value
    return env


def write_env_file(filepath: Path, env: Dict[str, str], header: str = "") -> None:
    """Write env dict to file."""
    with open(filepath, "w", encoding="utf-8") as f:
        if header:
            f.write(header)
            f.write("\n")
        for key, value in sorted(env.items()):
            # Quote values with spaces or special chars
            if " " in value or "'" in value or '"' in value:
                value = f'"{value}"'
            f.write(f"{key}={value}\n")


def set_secure_permissions(filepath: Path) -> bool:
    """Set file permissions to 600 (owner read/write only).

    Returns True if successful, False otherwise.
    """
    try:
        filepath.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return True
    except OSError as e:
        print(f"Warning: Could not set permissions on {filepath}: {e}", file=sys.stderr)
        return False


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Find repository root by looking for .git directory."""
    if start is None:
        start = Path.cwd()

    current = start.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    # Fallback to script location
    return Path(__file__).parent.parent.parent


def ensure_env_local(repo_root: Path) -> int:
    """Ensure backend/.env.local exists with required values.

    Returns 0 on success, 1 on error.
    """
    env_local_path = repo_root / "backend" / ".env.local"
    env_example_path = repo_root / "backend" / ".env.local.example"

    created = False
    modified = False

    # Load existing env.local or start fresh
    if env_local_path.exists():
        print(f"Found existing: {env_local_path}")
        env = parse_env_file(env_local_path)
    else:
        print(f"Creating new: {env_local_path}")
        # Start with defaults from example if it exists
        if env_example_path.exists():
            env = parse_env_file(env_example_path)
            # Remove commented-out keys (they'd have been skipped anyway)
        else:
            env = {}
        created = True

    # Required keys and their generators/defaults
    required_keys = {
        "GUAC_ENABLED": "true",
        "GUAC_BASE_URL": "http://127.0.0.1:8081/guacamole",
        "GUAC_ADMIN_USER": "guacadmin",
        "GUAC_ADMIN_PASSWORD": "guacadmin",
        "GUACD_CONTAINER_NAME": "octolab-guacd",
    }

    # Keys that need secure generation
    generated_keys = {
        "GUAC_ENC_KEY": generate_fernet_key,
    }

    # Ensure required keys exist
    for key, default in required_keys.items():
        if key not in env:
            env[key] = default
            redacted = redact_value(key, default)
            print(f"  Set {key}={redacted}")
            modified = True
        else:
            redacted = redact_value(key, env[key])
            print(f"  Existing {key}={redacted}")

    # Ensure generated keys exist (never overwrite!)
    for key, generator in generated_keys.items():
        if key not in env:
            value = generator()
            env[key] = value
            print(f"  Generated {key}=**** (new)")
            modified = True
        else:
            print(f"  Existing {key}=**** (preserved)")

    # Write file if created or modified
    if created or modified:
        header = """\
# backend/.env.local
# Auto-generated by ensure_env_local.py
# DO NOT COMMIT - contains secrets
#
# To regenerate defaults (preserving GUAC_ENC_KEY):
#   rm backend/.env.local && make dev-up
#
# WARNING: Do not change GUAC_ENC_KEY after labs have been created!
"""
        write_env_file(env_local_path, env, header)
        print(f"Wrote: {env_local_path}")

        # Set secure permissions
        if set_secure_permissions(env_local_path):
            print(f"Set permissions: 600 (owner read/write only)")
    else:
        print("No changes needed.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure backend/.env.local exists with required secrets."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root path (auto-detected if not specified)",
    )

    args = parser.parse_args()

    repo_root = args.repo_root or find_repo_root()
    print(f"Repository root: {repo_root}")

    return ensure_env_local(repo_root)


if __name__ == "__main__":
    sys.exit(main())
