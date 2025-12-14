"""Diagnose lab runtime status (admin-only).

This script inspects a single lab's runtime status for debugging purposes.

ADMIN-ONLY: Do not expose this via HTTP endpoints. Run directly by admins.

Usage:
    python -m app.scripts.diagnose_lab_runtime --lab-id <uuid>

Security:
- Does not accept tenant/user IDs
- Does not print owner_id (redacted if needed)
- Outputs diagnostic information only
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.lab import Lab
from app.runtime import get_runtime
from app.runtime.k8s_runtime import K8sLabRuntime
from app.services.novnc_probe import probe_novnc_ready, NovncNotReady
from app.utils.diagnostics import collect_compose_diagnostics, redact_owner_id, format_diagnostics_for_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def diagnose_lab(lab_id_str: str) -> None:
    """Diagnose a single lab's runtime status.

    Args:
        lab_id_str: Lab ID as string (UUID)
    """
    # Parse lab ID
    try:
        lab_id = UUID(lab_id_str)
    except ValueError:
        logger.error(f"Invalid lab ID format: {lab_id_str}")
        sys.exit(1)

    # Fetch lab from database
    async with AsyncSessionLocal() as session:
        lab = await session.get(Lab, lab_id)

        if not lab:
            logger.error(f"Lab {lab_id} not found in database")
            sys.exit(1)

        # Print lab basic info (redact owner)
        owner_redacted = redact_owner_id(lab.owner_id)
        print("\n" + "=" * 80)
        print("LAB DIAGNOSTICS")
        print("=" * 80)
        print(f"Lab ID:        {lab.id}")
        print(f"Owner:         {owner_redacted} (redacted)")
        print(f"Status:        {lab.status.value}")
        print(f"Recipe ID:     {lab.recipe_id}")
        print(f"Connection URL: {lab.connection_url or 'None'}")
        print(f"Created:       {lab.created_at}")
        print(f"Updated:       {lab.updated_at}")
        print(f"Finished:      {lab.finished_at or 'None'}")

        # Determine runtime type
        runtime = get_runtime()
        is_k8s = isinstance(runtime, K8sLabRuntime)

        print(f"\nRuntime Type:  {'Kubernetes' if is_k8s else 'Docker Compose'}")

        if is_k8s:
            print("\nKubernetes diagnostics not yet implemented.")
            print("Use kubectl commands to inspect lab resources:")
            print(f"  kubectl get all -n octolab-labs -l lab_id={lab.id}")
            return

        # Compose runtime diagnostics
        novnc_port = lab.novnc_host_port
        print(f"noVNC Port:    {novnc_port or 'Not allocated'}")

        if novnc_port:
            # Expected URL
            bind_host = settings.novnc_bind_addr
            expected_url = f"http://{bind_host}:{novnc_port}/vnc.html?lab_id={lab.id}"
            print(f"Expected URL:  {expected_url}")

            # Quick probe test
            print("\n" + "-" * 80)
            print("READINESS PROBE TEST")
            print("-" * 80)

            try:
                await probe_novnc_ready(
                    host=bind_host,
                    port=novnc_port,
                    timeout_seconds=10.0,  # Short timeout for diagnostic
                    poll_interval_seconds=1.0,
                    paths=settings.novnc_ready_paths,
                )
                print("✓ Readiness probe SUCCEEDED - noVNC is reachable")
            except NovncNotReady as e:
                print(f"✗ Readiness probe FAILED: {e}")
            except Exception as e:
                print(f"✗ Readiness probe ERROR: {type(e).__name__}: {e}")

        # Collect compose diagnostics
        print("\n" + "-" * 80)
        print("DOCKER COMPOSE DIAGNOSTICS")
        print("-" * 80)

        project_name = f"octolab_{lab.id}"
        print(f"Project Name:  {project_name}")

        diagnostics = await collect_compose_diagnostics(
            lab_id=lab.id,
            project_name=project_name,
            compose_file=None,
            max_log_lines=50,  # Fewer lines for manual inspection
        )

        print("\n--- compose ps ---")
        print(diagnostics.get("compose_ps", "No data"))

        print("\n--- compose logs (last 50 lines) ---")
        logs = diagnostics.get("compose_logs", "No data")
        # Truncate if too long
        if len(logs) > 5000:
            print(logs[:5000] + "\n... (truncated, use docker compose logs for full output)")
        else:
            print(logs)

        if "errors" in diagnostics:
            print(f"\n--- Errors during collection ---")
            print(diagnostics["errors"])

        print("\n" + "=" * 80)
        print("END DIAGNOSTICS")
        print("=" * 80)


async def main(lab_id: str) -> None:
    """Main entrypoint."""
    await diagnose_lab(lab_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="ADMIN-ONLY: Diagnose lab runtime status for debugging.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--lab-id",
        type=str,
        required=True,
        help="Lab ID (UUID) to diagnose",
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("ADMIN-ONLY DIAGNOSTIC TOOL: Lab Runtime Status")
    logger.info(f"Lab ID: {args.lab_id}")
    logger.info("=" * 80)

    asyncio.run(main(lab_id=args.lab_id))
