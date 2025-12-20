"""Nightly CVE exploit verification.

Run this script nightly via systemd timer to verify all CVEs with exploit
metadata are still exploitable. This catches regressions from:
- Docker image updates
- Dockerfile changes
- Infrastructure changes

Per CLAUDE.md: OctoLab is a REHEARSAL platform. If labs are misconfigured
and exploits fail, users may incorrectly conclude CVEs aren't exploitable,
potentially leaving their clients' systems vulnerable.

Notifications:
    Configure OCTOLAB_SLACK_WEBHOOK_URL and/or SMTP settings to receive
    alerts when verifications fail.

Usage:
    python -m app.scripts.nightly_cve_verification
    python -m app.scripts.nightly_cve_verification --cve CVE-2021-41773
    python -m app.scripts.nightly_cve_verification --failed-only
    python -m app.scripts.nightly_cve_verification --no-notify
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.cve_dockerfile import CVEDockerfile, VerificationStatus
from app.services.cve_smoke_test import verify_cve_exploit, CVESmokeTestResult
from app.services.notification_service import send_cve_verification_report

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def get_cves_to_verify(
    failed_only: bool = False,
    specific_cve: str | None = None,
) -> list[str]:
    """Get list of CVE IDs that have exploit metadata and should be verified."""
    async with AsyncSessionLocal() as db:
        query = select(CVEDockerfile.cve_id).where(
            CVEDockerfile.exploit_command.isnot(None),
            CVEDockerfile.expected_output.isnot(None),
        )

        if specific_cve:
            query = query.where(CVEDockerfile.cve_id == specific_cve.upper())
        elif failed_only:
            query = query.where(
                CVEDockerfile.verification_status == VerificationStatus.failed
            )

        result = await db.execute(query.order_by(CVEDockerfile.cve_id))
        return [row[0] for row in result.all()]


async def run_verification(cve_ids: list[str]) -> dict:
    """Run verification for all specified CVEs.

    Returns:
        Summary dict with passed, failed, and error counts
    """
    results = {
        "total": len(cve_ids),
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "details": [],
    }

    if not cve_ids:
        logger.info("No CVEs to verify")
        return results

    logger.info(f"Starting verification for {len(cve_ids)} CVE(s)")
    start_time = datetime.now(timezone.utc)

    for i, cve_id in enumerate(cve_ids, 1):
        logger.info(f"[{i}/{len(cve_ids)}] Verifying {cve_id}...")

        try:
            result: CVESmokeTestResult = await verify_cve_exploit(cve_id)

            if result.success:
                results["passed"] += 1
                logger.info(f"  PASSED ({result.duration_seconds:.1f}s)")
            else:
                results["failed"] += 1
                logger.warning(f"  FAILED: {result.error}")

            results["details"].append(result.to_dict())

        except Exception as e:
            results["errors"] += 1
            logger.exception(f"  ERROR: {type(e).__name__}: {e}")
            results["details"].append({
                "cve_id": cve_id,
                "success": False,
                "error": f"{type(e).__name__}: {e}",
            })

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    results["duration_seconds"] = elapsed

    logger.info("=" * 60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total:   {results['total']}")
    logger.info(f"Passed:  {results['passed']}")
    logger.info(f"Failed:  {results['failed']}")
    logger.info(f"Errors:  {results['errors']}")
    logger.info(f"Time:    {elapsed:.1f}s")
    logger.info("=" * 60)

    # Log failed CVEs for easy identification
    if results["failed"] > 0 or results["errors"] > 0:
        logger.warning("Failed/Error CVEs:")
        for detail in results["details"]:
            if not detail.get("success"):
                logger.warning(f"  - {detail['cve_id']}: {detail.get('error', 'unknown')[:100]}")

    return results


async def main(args: argparse.Namespace) -> int:
    """Main entry point."""
    logger.info("OctoLab Nightly CVE Verification")
    logger.info(f"Started at: {datetime.now(timezone.utc).isoformat()}")

    if args.cve:
        logger.info(f"Mode: Single CVE ({args.cve})")
    elif args.failed_only:
        logger.info("Mode: Failed CVEs only")
    else:
        logger.info("Mode: All CVEs with exploit metadata")

    if args.no_notify:
        logger.info("Notifications: Disabled")

    # Get CVEs to verify
    cve_ids = await get_cves_to_verify(
        failed_only=args.failed_only,
        specific_cve=args.cve,
    )

    if not cve_ids:
        logger.info("No CVEs found matching criteria")
        return 0

    # Run verification
    results = await run_verification(cve_ids)

    # Send notifications (always sends full report)
    if not args.no_notify:
        logger.info("Sending verification report...")
        try:
            notify_results = await send_cve_verification_report(
                total=results["total"],
                passed=results["passed"],
                failed=results["failed"],
                errors=results["errors"],
                duration_seconds=results["duration_seconds"],
                details=results["details"],
            )
            for channel, success in notify_results.items():
                if success:
                    logger.info(f"  {channel}: sent")
                else:
                    logger.warning(f"  {channel}: failed to send")
        except Exception as e:
            logger.exception(f"Failed to send notifications: {e}")

    # Return non-zero exit code if any failures
    if results["failed"] > 0 or results["errors"] > 0:
        return 1

    return 0


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Nightly CVE exploit verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--cve",
        type=str,
        help="Verify a specific CVE ID only",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Only re-verify CVEs that previously failed",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable Slack/email notifications",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
