"""CVE Metadata Cache Model - stores NVD data."""

from sqlalchemy import String, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class CVEMetadata(Base, TimestampMixin):
    """Cached NVD data for a CVE. Fetch once, use forever."""

    __tablename__ = "cve_metadata"

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)

    # From NVD
    description: Mapped[str | None] = mapped_column(Text)
    cvss_score: Mapped[float | None] = mapped_column(Float)
    cvss_severity: Mapped[str | None] = mapped_column(String(20))  # LOW, MEDIUM, HIGH, CRITICAL
    affected_products: Mapped[dict | None] = mapped_column(JSONB, default=list)
    references: Mapped[dict | None] = mapped_column(JSONB, default=list)
