#!/usr/bin/env python3
"""Generate Guacamole initdb.sql from the exact image tag in docker-compose.yml.

This script ensures the DB schema always matches the Guacamole image version.
It extracts the guacamole image tag from the compose file and runs the
container's initdb.sh script to generate the matching SQL.

Usage:
    python3 dev/scripts/guac_generate_initdb.py

    # Dry-run (print SQL to stdout, don't write file)
    python3 dev/scripts/guac_generate_initdb.py --dry-run

Exit codes:
    0 - Success
    1 - Generation failed
    2 - Configuration error (compose file not found, etc.)

SECURITY:
- Uses subprocess with shell=False
- Never evals or sources external files
- Validates image tag format before use
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ============================================================================
# Configuration
# ============================================================================

# Paths relative to repo root
COMPOSE_FILE = "infra/guacamole/docker-compose.yml"
INITDB_OUTPUT = "infra/guacamole/init/initdb.sql"

# Commands to try inside the container (in order)
# Note: The flag is --postgresql (not --postgres)
INITDB_COMMANDS = [
    ["/opt/guacamole/bin/initdb.sh", "--postgresql"],
    ["/usr/local/bin/initdb.sh", "--postgresql"],
    ["initdb.sh", "--postgresql"],
]

# Regex to validate image tag format (prevent injection)
IMAGE_TAG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*:[a-zA-Z0-9._-]+$")


# ============================================================================
# Color output
# ============================================================================

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'


def log_info(msg: str) -> None:
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)


# ============================================================================
# Image tag extraction
# ============================================================================

def find_repo_root() -> Path:
    """Find the repository root by looking for known markers."""
    current = Path(__file__).resolve().parent
    for _ in range(10):  # Prevent infinite loop
        if (current / "Makefile").exists() and (current / "backend").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError("Could not find repository root")


def get_guacamole_image_tag(compose_path: Path) -> str:
    """Extract Guacamole image tag from docker-compose.yml using docker compose config.

    Uses `docker compose config` to resolve the compose file and extract
    the exact image tag being used.

    Args:
        compose_path: Path to docker-compose.yml

    Returns:
        Full image tag (e.g., "guacamole/guacamole:1.5.5")

    Raises:
        RuntimeError: If extraction fails
    """
    if not compose_path.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_path}")

    # Use docker compose config to get resolved configuration
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "config"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker compose config failed: {result.stderr}")

        config_output = result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError("docker compose config timed out")
    except FileNotFoundError:
        raise RuntimeError("docker command not found")

    # Parse the output to find guacamole service image
    # Looking for pattern like:
    #   guacamole:
    #     ...
    #     image: guacamole/guacamole:1.5.5
    in_guacamole_service = False
    indent_level = 0

    for line in config_output.split("\n"):
        # Track indentation to know when we leave a service block
        if line.strip():
            current_indent = len(line) - len(line.lstrip())
        else:
            continue

        stripped = line.strip()

        # Check if we're entering the guacamole service block (at services level, indented 2 spaces)
        if stripped == "guacamole:" and current_indent == 2:
            in_guacamole_service = True
            indent_level = current_indent
            continue

        # Check if we're leaving the guacamole service block (another service at same or lower indent)
        if in_guacamole_service and current_indent <= indent_level and stripped.endswith(":") and not stripped.startswith("image"):
            in_guacamole_service = False
            continue

        # Look for image line within guacamole service (more indented than service name)
        if in_guacamole_service and current_indent > indent_level and stripped.startswith("image:"):
            # The format is "image: guacamole/guacamole:1.5.5"
            # Split only on first colon+space to get the value
            parts = stripped.split(": ", 1)
            if len(parts) == 2:
                image = parts[1].strip()
                # Validate image tag format
                if not IMAGE_TAG_PATTERN.match(image):
                    raise RuntimeError(f"Invalid image tag format: {image}")
                return image

    raise RuntimeError("Could not find guacamole service image in compose config")


# ============================================================================
# InitDB generation
# ============================================================================

def generate_initdb_sql(image_tag: str) -> str:
    """Generate initdb.sql by running the container's initdb.sh script.

    Args:
        image_tag: Full image tag (e.g., "guacamole/guacamole:1.5.5")

    Returns:
        SQL content for initializing the database

    Raises:
        RuntimeError: If generation fails
    """
    log_info(f"Pulling image {image_tag}...")

    # Pull the image first to ensure we have it
    try:
        result = subprocess.run(
            ["docker", "pull", image_tag],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes for pull
        )
        if result.returncode != 0:
            log_warn(f"docker pull returned non-zero: {result.stderr}")
            # Continue anyway - image might already be cached
    except subprocess.TimeoutExpired:
        raise RuntimeError("docker pull timed out")

    # Try each initdb command location
    for cmd in INITDB_COMMANDS:
        log_info(f"Trying: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    image_tag,
                ] + cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Validate output looks like SQL
                output = result.stdout
                if "CREATE TABLE" in output or "CREATE SCHEMA" in output:
                    log_info(f"Successfully generated SQL using: {' '.join(cmd)}")
                    return output
                else:
                    log_warn(f"Output doesn't look like SQL, trying next command...")
            else:
                log_warn(f"Command failed or empty output, trying next...")

        except subprocess.TimeoutExpired:
            log_warn(f"Command timed out, trying next...")
            continue

    raise RuntimeError("All initdb.sh command locations failed")


def write_initdb_atomically(sql_content: str, output_path: Path, image_tag: str) -> None:
    """Write initdb.sql atomically using rename.

    Args:
        sql_content: SQL content to write
        output_path: Target file path
        image_tag: Image tag used to generate this SQL (for header comment)
    """
    import datetime

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then atomic rename
    fd, temp_path = tempfile.mkstemp(
        suffix=".sql",
        prefix="initdb_",
        dir=output_path.parent,
    )
    try:
        with os.fdopen(fd, "w") as f:
            # Add header comment with image tag and timestamp
            f.write("-- AUTO-GENERATED by guac_generate_initdb.py\n")
            f.write(f"-- Image: {image_tag}\n")
            f.write(f"-- Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n")
            f.write("-- Do not edit manually. Re-run the generator to update.\n")
            f.write("--\n\n")
            f.write(sql_content)

        # Set permissions to 644 (world-readable) so postgres container can read it
        os.chmod(temp_path, 0o644)

        # Atomic rename
        os.rename(temp_path, output_path)
        log_info(f"Wrote: {output_path}")
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    """Main entry point."""
    # Parse args
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    try:
        repo_root = find_repo_root()
    except FileNotFoundError as e:
        log_error(str(e))
        return 2

    compose_path = repo_root / COMPOSE_FILE
    output_path = repo_root / INITDB_OUTPUT

    print(f"\n{Colors.BLUE}=== Guacamole InitDB Generator ==={Colors.NC}")
    print(f"  Compose file: {compose_path}")
    print(f"  Output: {output_path}")
    print()

    # Step 1: Get image tag
    try:
        image_tag = get_guacamole_image_tag(compose_path)
        log_info(f"Detected guacamole image: {image_tag}")
    except (FileNotFoundError, RuntimeError) as e:
        log_error(f"Failed to get image tag: {e}")
        return 2

    # Step 2: Generate SQL
    try:
        sql_content = generate_initdb_sql(image_tag)
    except RuntimeError as e:
        log_error(f"Failed to generate initdb.sql: {e}")
        return 1

    # Step 3: Output
    if dry_run:
        print(f"\n{Colors.YELLOW}=== DRY RUN - SQL Output ==={Colors.NC}")
        print(sql_content)
        print(f"\n{Colors.YELLOW}=== END DRY RUN ==={Colors.NC}")
        log_info("Dry run complete. No files written.")
    else:
        try:
            write_initdb_atomically(sql_content, output_path, image_tag)
        except Exception as e:
            log_error(f"Failed to write output: {e}")
            return 1

    print()
    log_info(f"{Colors.GREEN}InitDB generation complete!{Colors.NC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
