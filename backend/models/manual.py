"""Manual and chunk models for document storage."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class Manual(Base, UUIDMixin, TimestampMixin):
    """Represents an uploaded HVAC manual."""

    __tablename__ = "manuals"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    model_series: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # air_conditioner, heat_pump, furnace, etc.
    document_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # service_manual, installation_guide, parts_catalog, etc.

    # File info
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # Processing status
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Metadata
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ManualChunk(Base, UUIDMixin):
    """A chunk of text from a manual stored for retrieval."""

    __tablename__ = "manual_chunks"

    manual_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # troubleshooting_step, specification, procedure, safety_warning, error_code, general

    # Location info
    page_numbers: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    parent_section: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    has_image_reference: Mapped[bool] = mapped_column(Boolean, default=False)

    # Equipment context (denormalized for filtering)
    brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    system_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Search metadata
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    error_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)

    # Vector store reference
    vector_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class ManualImage(Base, UUIDMixin):
    """Images extracted from manuals (diagrams, schematics)."""

    __tablename__ = "manual_images"

    manual_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Storage
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)  # png, jpg, etc.

    # AI-generated description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # wiring_diagram, refrigerant_flow, exploded_view, etc.
    components_identified: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
