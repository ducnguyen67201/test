"""CVE Dockerfile Registry Model."""

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Text, Integer, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class CVEDockerfileStatus(str, enum.Enum):
    """Status of a CVE Dockerfile entry."""

    curated = "curated"  # Human-verified
    llm_validated = "llm_validated"  # LLM-generated, tested successfully
    llm_pending = "llm_pending"  # LLM-generated, not yet tested
    needs_review = "needs_review"  # Failed validation, needs human review


class VerificationType(str, enum.Enum):
    """How to verify exploit output."""

    contains = "contains"  # expected_output is substring of actual
    regex = "regex"  # expected_output is regex pattern
    status_code = "status_code"  # HTTP status code check
    exit_code = "exit_code"  # Command exit code check


class VerificationStatus(str, enum.Enum):
    """Result of exploit verification."""

    untested = "untested"
    passed = "passed"
    failed = "failed"


class CVEDockerfile(Base, TimestampMixin):
    """Stores validated Dockerfiles for specific CVEs."""

    __tablename__ = "cve_dockerfiles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    cve_id: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
        nullable=False,
    )

    # Aliases for common names (e.g., "log4shell", "react2shell")
    aliases: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(100)),
        default=list,
        nullable=True,
    )

    # Dockerfile content
    dockerfile: Mapped[str] = mapped_column(Text, nullable=False)
    source_files: Mapped[dict | None] = mapped_column(JSONB, default=list)

    # Metadata
    base_image: Mapped[str | None] = mapped_column(String(255))
    exposed_ports: Mapped[dict | None] = mapped_column(JSONB, default=list)
    exploit_hint: Mapped[str | None] = mapped_column(Text)

    # Validation status
    status: Mapped[CVEDockerfileStatus] = mapped_column(
        SQLEnum(CVEDockerfileStatus),
        default=CVEDockerfileStatus.llm_pending,
    )

    # LLM confidence scoring
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance
    created_by: Mapped[str | None] = mapped_column(String(100))

    # Exploit verification metadata
    exploit_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    exploit_steps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # For multi-step exploits
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_type: Mapped[VerificationType | None] = mapped_column(
        SQLEnum(VerificationType, name="verificationtype"),
        nullable=True,
    )
    exploit_timeout_seconds: Mapped[int | None] = mapped_column(
        Integer, default=30, nullable=True
    )

    # Verification state
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verification_status: Mapped[VerificationStatus | None] = mapped_column(
        SQLEnum(VerificationStatus, name="verificationstatus"),
        default=VerificationStatus.untested,
        nullable=True,
    )
    last_verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
