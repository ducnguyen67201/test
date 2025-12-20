"""Dockerfile Review Queue API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.dockerfile_review_queue import DockerfileReviewQueue
from app.api.deps import get_current_user_or_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dockerfile-review-queue", tags=["Review Queue"])


class ReviewQueueCreate(BaseModel):
    cve_id: str = Field(..., max_length=20)
    recipe_name: str = Field(..., max_length=255)
    last_dockerfile: Optional[str] = None
    errors: list[str] = []
    attempts: int = 0
    confidence_score: Optional[int] = Field(None, ge=0, le=100)
    confidence_reason: Optional[str] = None


class ReviewQueueResponse(BaseModel):
    id: str
    cve_id: str
    recipe_name: str
    last_dockerfile: Optional[str]
    errors: list[str]
    attempts: int
    status: str
    confidence_score: Optional[int]
    confidence_reason: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ReviewQueueResponse])
async def list_review_queue(
    queue_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_or_service),
):
    """List items in the review queue."""
    query = select(DockerfileReviewQueue)

    if queue_status:
        query = query.where(DockerfileReviewQueue.status == queue_status)

    query = query.order_by(DockerfileReviewQueue.created_at.desc()).limit(limit)
    result = await db.execute(query)
    entries = result.scalars().all()

    return [
        ReviewQueueResponse(
            id=str(e.id),
            cve_id=e.cve_id,
            recipe_name=e.recipe_name,
            last_dockerfile=e.last_dockerfile,
            errors=e.errors or [],
            attempts=e.attempts,
            status=e.status,
            confidence_score=e.confidence_score,
            confidence_reason=e.confidence_reason,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in entries
    ]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_review_queue_entry(
    data: ReviewQueueCreate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_or_service),
):
    """Add a failed Dockerfile to the review queue."""
    from app.services.notification_service import send_dockerfile_review_alert

    entry = DockerfileReviewQueue(
        cve_id=data.cve_id.upper(),
        recipe_name=data.recipe_name,
        last_dockerfile=data.last_dockerfile,
        errors=data.errors,
        attempts=data.attempts,
        status="pending",
        confidence_score=data.confidence_score,
        confidence_reason=data.confidence_reason,
    )

    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info(f"Added to review queue: {entry.cve_id} ({entry.attempts} attempts)")

    # Send Discord/Slack alert with link to review page
    try:
        await send_dockerfile_review_alert(
            review_id=str(entry.id),
            cve_id=entry.cve_id,
            recipe_name=entry.recipe_name,
            attempts=entry.attempts,
            errors=entry.errors or [],
            confidence_score=entry.confidence_score,
        )
    except Exception as e:
        logger.warning(f"Failed to send review queue alert: {e}")

    return {"id": str(entry.id), "cve_id": entry.cve_id}


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review_queue_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_or_service),
):
    """Delete a review queue entry."""
    from uuid import UUID

    try:
        uuid_id = UUID(entry_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid entry ID format",
        )

    result = await db.execute(
        select(DockerfileReviewQueue).where(DockerfileReviewQueue.id == uuid_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        )

    await db.delete(entry)
    await db.commit()
    logger.info(f"Deleted review queue entry: {entry.cve_id}")


@router.get("/{entry_id}", response_model=ReviewQueueResponse)
async def get_review_queue_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_or_service),
):
    """Get a single review queue entry."""
    from uuid import UUID

    try:
        uuid_id = UUID(entry_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid entry ID format",
        )

    result = await db.execute(
        select(DockerfileReviewQueue).where(DockerfileReviewQueue.id == uuid_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        )

    return ReviewQueueResponse(
        id=str(entry.id),
        cve_id=entry.cve_id,
        recipe_name=entry.recipe_name,
        last_dockerfile=entry.last_dockerfile,
        errors=entry.errors or [],
        attempts=entry.attempts,
        status=entry.status,
        confidence_score=entry.confidence_score,
        confidence_reason=entry.confidence_reason,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
    )


class ApproveRequest(BaseModel):
    fixed_dockerfile: str
    fixed_source_files: list[dict] = []
    base_image: Optional[str] = None
    exposed_ports: list[int] = []
    exploit_hint: Optional[str] = None
    aliases: list[str] = []


@router.post("/{entry_id}/approve")
async def approve_review_entry(
    entry_id: str,
    data: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Approve a review entry and promote to CVE registry."""
    from uuid import UUID
    from datetime import datetime, timezone
    from app.models.cve_dockerfile import CVEDockerfile, CVEDockerfileStatus

    try:
        uuid_id = UUID(entry_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid entry ID format",
        )

    result = await db.execute(
        select(DockerfileReviewQueue).where(DockerfileReviewQueue.id == uuid_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        )

    # Check if CVE already exists in registry
    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == entry.cve_id)
    )
    existing = result.scalar_one_or_none()

    user_email = getattr(current_user, "email", "service")

    # Clean aliases (lowercase, dedupe)
    clean_aliases = list(set(a.strip().lower() for a in data.aliases if a.strip()))

    if existing:
        # Update existing entry
        existing.dockerfile = data.fixed_dockerfile
        existing.source_files = data.fixed_source_files
        existing.base_image = data.base_image
        existing.exposed_ports = data.exposed_ports
        existing.exploit_hint = data.exploit_hint
        existing.aliases = clean_aliases
        existing.status = CVEDockerfileStatus.curated
    else:
        # Create new registry entry
        cve_entry = CVEDockerfile(
            cve_id=entry.cve_id,
            dockerfile=data.fixed_dockerfile,
            source_files=data.fixed_source_files,
            base_image=data.base_image,
            exposed_ports=data.exposed_ports,
            exploit_hint=data.exploit_hint,
            aliases=clean_aliases,
            status=CVEDockerfileStatus.curated,
            created_by=f"review:{user_email}",
        )
        db.add(cve_entry)

    # Mark review as approved
    entry.status = "approved"
    entry.reviewed_by = user_email
    entry.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    logger.info(f"Approved review entry {entry.cve_id} by {user_email}")

    return {"status": "approved", "cve_id": entry.cve_id}


class TestBuildRequest(BaseModel):
    dockerfile: str
    source_files: list[dict] = []


class TestBuildResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    logs: Optional[str] = None
    duration_seconds: Optional[float] = None


@router.post("/test-build", response_model=TestBuildResponse)
async def test_build_dockerfile(
    data: TestBuildRequest,
    _current_user=Depends(get_current_user_or_service),
):
    """Test build a Dockerfile in a sandboxed environment.

    Returns build success/failure with logs.
    """
    import tempfile
    import subprocess
    import time
    import shutil
    from pathlib import Path

    start_time = time.time()
    build_dir = None

    try:
        # Create temp build context
        build_dir = tempfile.mkdtemp(prefix="dockerfile_test_")
        build_path = Path(build_dir)

        # Write Dockerfile
        dockerfile_path = build_path / "Dockerfile"
        dockerfile_path.write_text(data.dockerfile)

        # Write source files
        for src_file in data.source_files:
            file_path = build_path / src_file.get("filename", "file")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(src_file.get("content", ""))

        # Generate unique tag for this test
        test_tag = f"octolab-test-build:{int(time.time())}"

        # Run docker build with timeout
        result = subprocess.run(
            [
                "docker", "build",
                "--no-cache",
                "-t", test_tag,
                ".",
            ],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )

        duration = time.time() - start_time

        # Clean up test image
        subprocess.run(
            ["docker", "rmi", "-f", test_tag],
            capture_output=True,
            timeout=10,
        )

        if result.returncode == 0:
            logger.info(f"Test build succeeded in {duration:.1f}s")
            return TestBuildResponse(
                success=True,
                logs=result.stdout[-5000:] if result.stdout else None,  # Last 5KB
                duration_seconds=duration,
            )
        else:
            logger.warning(f"Test build failed: {result.stderr[:500]}")
            return TestBuildResponse(
                success=False,
                error=result.stderr[-3000:] if result.stderr else "Build failed",
                logs=result.stdout[-2000:] if result.stdout else None,
                duration_seconds=duration,
            )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logger.warning("Test build timed out")
        return TestBuildResponse(
            success=False,
            error="Build timed out after 120 seconds",
            duration_seconds=duration,
        )
    except Exception as e:
        duration = time.time() - start_time
        logger.exception(f"Test build error: {e}")
        return TestBuildResponse(
            success=False,
            error=str(e),
            duration_seconds=duration,
        )
    finally:
        # Cleanup temp directory
        if build_dir:
            try:
                shutil.rmtree(build_dir)
            except Exception:
                pass


class RejectRequest(BaseModel):
    reason: str = "Invalid or unsupported CVE"


@router.post("/{entry_id}/reject")
async def reject_review_entry(
    entry_id: str,
    data: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Reject a review entry."""
    from uuid import UUID
    from datetime import datetime, timezone

    try:
        uuid_id = UUID(entry_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid entry ID format",
        )

    result = await db.execute(
        select(DockerfileReviewQueue).where(DockerfileReviewQueue.id == uuid_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        )

    user_email = getattr(current_user, "email", "service")

    entry.status = "rejected"
    entry.reviewed_by = user_email
    entry.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    logger.info(f"Rejected review entry {entry.cve_id}: {data.reason}")

    return {"status": "rejected", "cve_id": entry.cve_id, "reason": data.reason}
