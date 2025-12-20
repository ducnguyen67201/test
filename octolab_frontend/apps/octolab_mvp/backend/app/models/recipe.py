"""Recipe model."""

from uuid import UUID, uuid4

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin


class Recipe(Base, TimestampMixin):
    """Recipe model for vulnerability templates and lab configurations."""

    __tablename__ = "recipes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=None,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    software: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    version_constraint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    exploit_family: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    labs: Mapped[list["Lab"]] = relationship(
        "Lab",
        back_populates="recipe",
    )

