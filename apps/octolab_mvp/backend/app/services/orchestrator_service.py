"""Orchestrator service for advancing lab states in batch operations."""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.lab import Lab, LabStatus


def advance_lab_states(session: Session) -> dict[str, int]:
    """Advance labs through their lifecycle.

    Transitions:
    - REQUESTED → READY
    - ENDING → FINISHED (sets finished_at timestamp)

    Args:
        session: Sync SQLAlchemy session

    Returns:
        Dictionary with counts: {"to_ready": int, "to_finished": int}
    """
    # Move REQUESTED → READY
    stmt_ready = (
        update(Lab)
        .where(Lab.status == LabStatus.REQUESTED)
        .values(status=LabStatus.READY)
    )
    result_ready = session.execute(stmt_ready)
    to_ready_count = result_ready.rowcount

    # Move ENDING -> FINISHED only for labs where teardown has already completed
    # Teardown paths (terminate_lab or force teardown) must set finished_at when done.
    stmt_finished = (
        update(Lab)
        .where(Lab.status == LabStatus.ENDING)
        .where(Lab.finished_at.is_not(None))
        .values(
            status=LabStatus.FINISHED,
        )
    )
    result_finished = session.execute(stmt_finished)
    to_finished_count = result_finished.rowcount

    # Commit all changes at once
    session.commit()

    return {
        "to_ready": to_ready_count,
        "to_finished": to_finished_count,
    }

