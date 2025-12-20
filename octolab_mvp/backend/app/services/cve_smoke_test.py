"""CVE exploit verification smoke tests.

This service verifies that CVE labs are actually exploitable by:
1. Spawning a lab with the CVE Dockerfile
2. Waiting for it to be ready
3. Executing the exploit command from OctoBox
4. Verifying the output matches expected pattern
5. Tearing down the lab
6. Updating verification status in database

Per CLAUDE.md: OctoLab is a REHEARSAL platform. If our lab is misconfigured
and the exploit fails, users may incorrectly conclude the CVE isn't exploitable,
potentially leaving their clients' systems vulnerable.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models.cve_dockerfile import (
    CVEDockerfile,
    VerificationStatus,
    VerificationType,
)
from app.models.lab import Lab, LabStatus
from app.models.recipe import Recipe
from app.models.user import User
from app.services.lab_service import provision_lab
from app.services.firecracker_manager import send_agent_command

logger = logging.getLogger(__name__)

# Default timeout for exploit commands (seconds)
DEFAULT_EXPLOIT_TIMEOUT = 30

# Maximum time to wait for lab to be ready (seconds)
LAB_READY_TIMEOUT = 120


class CVESmokeTestResult:
    """Result of a CVE smoke test."""

    def __init__(
        self,
        cve_id: str,
        success: bool,
        verification_status: VerificationStatus,
        error: Optional[str] = None,
        actual_output: Optional[str] = None,
        duration_seconds: float = 0,
    ):
        self.cve_id = cve_id
        self.success = success
        self.verification_status = verification_status
        self.error = error
        self.actual_output = actual_output
        self.duration_seconds = duration_seconds

    def to_dict(self) -> dict:
        return {
            "cve_id": self.cve_id,
            "success": self.success,
            "verification_status": self.verification_status.value,
            "error": self.error,
            "actual_output": self.actual_output[:500] if self.actual_output else None,
            "duration_seconds": round(self.duration_seconds, 2),
        }


async def verify_cve_exploit(cve_id: str) -> CVESmokeTestResult:
    """
    Run a full smoke test for a CVE.

    1. Look up CVE in registry with exploit metadata
    2. Create a recipe and lab for the CVE
    3. Wait for lab to be ready
    4. Execute exploit from OctoBox
    5. Verify output
    6. Teardown and update status

    Returns:
        CVESmokeTestResult with pass/fail status
    """
    start_time = datetime.now(timezone.utc)
    cve_id = cve_id.upper()
    lab_id = None

    logger.info(f"[CVE Smoke] Starting verification for {cve_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Get CVE record with exploit metadata
            result = await db.execute(
                select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id)
            )
            cve_entry = result.scalar_one_or_none()

            if not cve_entry:
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.failed,
                    error=f"CVE {cve_id} not found in registry",
                    duration_seconds=_elapsed(start_time),
                )

            if not cve_entry.exploit_command:
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.untested,
                    error="No exploit_command defined for this CVE",
                    duration_seconds=_elapsed(start_time),
                )

            if not cve_entry.expected_output:
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.untested,
                    error="No expected_output defined for this CVE",
                    duration_seconds=_elapsed(start_time),
                )

            # 2. Get or create a test user for smoke tests
            test_user = await _get_or_create_smoke_test_user(db)

            # 3. Get or create a recipe for this CVE
            recipe = await _get_or_create_cve_recipe(db, cve_entry)

            # 4. Create lab with runtime_meta containing dockerfile
            runtime_meta = {
                "dockerfile": cve_entry.dockerfile,
                "source_files": cve_entry.source_files or [],
                "base_image": cve_entry.base_image,
                "exposed_ports": cve_entry.exposed_ports or [],
            }
            lab = Lab(
                id=uuid4(),
                owner_id=test_user.id,
                recipe_id=recipe.id,
                status=LabStatus.PROVISIONING,
                runtime="firecracker",
                runtime_meta=runtime_meta,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(lab)
            await db.commit()
            await db.refresh(lab)
            lab_id = lab.id

            logger.info(f"[CVE Smoke] Created lab {lab_id} for {cve_id}")

            # 5. Provision lab (run synchronously since we need to wait)
            await provision_lab(lab_id)

            # 6. Wait for lab to be ready
            lab = await _wait_for_lab_ready(db, lab_id, timeout=LAB_READY_TIMEOUT)

            if lab.status != LabStatus.READY:
                error_msg = f"Lab failed to reach READY state: {lab.status.value}"
                await _update_verification_status(
                    db, cve_entry, VerificationStatus.failed, error_msg
                )
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.failed,
                    error=error_msg,
                    duration_seconds=_elapsed(start_time),
                )

            logger.info(f"[CVE Smoke] Lab {lab_id} is ready, running exploit")

            # 7. Execute exploit command
            timeout = cve_entry.exploit_timeout_seconds or DEFAULT_EXPLOIT_TIMEOUT
            actual_output, exec_error = await _exec_exploit_in_octobox(
                str(lab_id),
                cve_entry.exploit_command,
                timeout=timeout,
            )

            if exec_error:
                await _update_verification_status(
                    db, cve_entry, VerificationStatus.failed, exec_error
                )
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.failed,
                    error=exec_error,
                    actual_output=actual_output,
                    duration_seconds=_elapsed(start_time),
                )

            # 8. Verify output
            verify_type = cve_entry.verification_type or VerificationType.contains
            is_match = _verify_output(
                actual_output or "",
                cve_entry.expected_output,
                verify_type,
            )

            if is_match:
                await _update_verification_status(
                    db, cve_entry, VerificationStatus.passed, None
                )
                logger.info(f"[CVE Smoke] {cve_id} PASSED verification")
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=True,
                    verification_status=VerificationStatus.passed,
                    actual_output=actual_output,
                    duration_seconds=_elapsed(start_time),
                )
            else:
                error_msg = f"Output mismatch: expected '{cve_entry.expected_output}' ({verify_type.value}) but got: {actual_output[:200] if actual_output else 'empty'}"
                await _update_verification_status(
                    db, cve_entry, VerificationStatus.failed, error_msg
                )
                logger.warning(f"[CVE Smoke] {cve_id} FAILED: {error_msg}")
                return CVESmokeTestResult(
                    cve_id=cve_id,
                    success=False,
                    verification_status=VerificationStatus.failed,
                    error=error_msg,
                    actual_output=actual_output,
                    duration_seconds=_elapsed(start_time),
                )

        except Exception as e:
            logger.exception(f"[CVE Smoke] Error verifying {cve_id}")
            error_msg = f"Verification error: {type(e).__name__}: {str(e)}"

            # Try to update status
            try:
                result = await db.execute(
                    select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id)
                )
                cve_entry = result.scalar_one_or_none()
                if cve_entry:
                    await _update_verification_status(
                        db, cve_entry, VerificationStatus.failed, error_msg
                    )
            except Exception:
                pass

            return CVESmokeTestResult(
                cve_id=cve_id,
                success=False,
                verification_status=VerificationStatus.failed,
                error=error_msg,
                duration_seconds=_elapsed(start_time),
            )

        finally:
            # 9. Teardown lab
            if lab_id:
                try:
                    await _teardown_lab(db, lab_id)
                    logger.info(f"[CVE Smoke] Lab {lab_id} torn down")
                except Exception as e:
                    logger.warning(f"[CVE Smoke] Failed to teardown lab {lab_id}: {e}")


async def _get_or_create_smoke_test_user(db: AsyncSession) -> User:
    """Get or create a dedicated user for smoke tests."""
    smoke_email = "cve-smoke-test@octolab.internal"

    result = await db.execute(select(User).where(User.email == smoke_email))
    user = result.scalar_one_or_none()

    if user:
        return user

    user = User(
        id=uuid4(),
        email=smoke_email,
        password_hash="not-a-real-password",  # Can't login
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _get_or_create_cve_recipe(db: AsyncSession, cve_entry: CVEDockerfile) -> Recipe:
    """Get or create a recipe for smoke testing this CVE."""
    recipe_name = f"CVE Smoke Test: {cve_entry.cve_id}"

    result = await db.execute(select(Recipe).where(Recipe.name == recipe_name))
    recipe = result.scalar_one_or_none()

    if recipe:
        return recipe

    # Recipe stores minimal metadata; dockerfile goes in lab.runtime_meta
    recipe = Recipe(
        id=uuid4(),
        name=recipe_name,
        description=f"Smoke test recipe for {cve_entry.cve_id}",
        software=cve_entry.base_image or "unknown",
    )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe


async def _wait_for_lab_ready(
    db: AsyncSession, lab_id, timeout: int = LAB_READY_TIMEOUT
) -> Lab:
    """Poll lab status until ready or timeout."""
    start = datetime.now(timezone.utc)

    while True:
        await db.refresh(await db.get(Lab, lab_id))
        lab = await db.get(Lab, lab_id)

        if lab.status == LabStatus.READY:
            return lab

        if lab.status in (LabStatus.FAILED, LabStatus.FINISHED):
            return lab

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        if elapsed > timeout:
            return lab

        await asyncio.sleep(2)


async def _exec_exploit_in_octobox(
    lab_id: str,
    command: str,
    timeout: int = DEFAULT_EXPLOIT_TIMEOUT,
) -> tuple[Optional[str], Optional[str]]:
    """
    Execute exploit command inside OctoBox container.

    Returns:
        (output, error) tuple
    """
    try:
        # Use agent's exec command to run inside octobox
        response = await send_agent_command(
            lab_id,
            "exec",
            timeout=timeout,
            container="octobox",
            cmd=command,  # Use 'cmd' to avoid collision with agent command
        )

        if response.ok:
            return response.stdout, None
        else:
            return response.stdout, response.stderr or response.error

    except Exception as e:
        return None, f"Exec failed: {type(e).__name__}: {str(e)}"


def _verify_output(actual: str, expected: str, verify_type: VerificationType) -> bool:
    """Check if actual output matches expected based on verification type."""
    if verify_type == VerificationType.contains:
        return expected in actual

    elif verify_type == VerificationType.regex:
        try:
            return bool(re.search(expected, actual, re.MULTILINE | re.DOTALL))
        except re.error:
            return False

    elif verify_type == VerificationType.status_code:
        # Expected is HTTP status code like "200"
        # Look for it in output
        return expected in actual

    elif verify_type == VerificationType.exit_code:
        # Expected is exit code like "0"
        return actual.strip() == expected

    return False


async def _update_verification_status(
    db: AsyncSession,
    cve_entry: CVEDockerfile,
    status: VerificationStatus,
    error: Optional[str],
) -> None:
    """Update CVE verification status in database."""
    cve_entry.verification_status = status
    cve_entry.last_verified_at = datetime.now(timezone.utc)
    cve_entry.last_verification_error = error
    await db.commit()


async def _teardown_lab(db: AsyncSession, lab_id) -> None:
    """Mark lab as ending to trigger teardown."""
    lab = await db.get(Lab, lab_id)
    if lab and lab.status not in (LabStatus.FINISHED, LabStatus.ENDING):
        lab.status = LabStatus.ENDING
        await db.commit()


def _elapsed(start: datetime) -> float:
    """Calculate elapsed seconds since start."""
    return (datetime.now(timezone.utc) - start).total_seconds()
