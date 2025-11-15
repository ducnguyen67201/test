"""Internal endpoints for orchestrator and administrative operations."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.services.orchestrator_service import advance_lab_states

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post(
    "/orchestrator/tick",
    summary="Trigger orchestrator to advance lab states",
    response_model=dict[str, int],
)
def orchestrator_tick(
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Advance lab states in bulk.

    This is an internal maintenance endpoint.

    Transitions:
    - REQUESTED → READY
    - ENDING → FINISHED

    Returns:
        Dictionary with counts: {"to_ready": int, "to_finished": int}
    """
    return advance_lab_states(session)

