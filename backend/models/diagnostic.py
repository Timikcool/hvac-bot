"""Diagnostic flowchart, terminology, and feedback correction models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UUIDMixin


class DiagnosticFlowchart(Base, UUIDMixin, TimestampMixin):
    """A diagnostic path for a specific symptom/equipment combination.

    Maps a symptom (e.g., "compressor not starting") to an ordered set
    of diagnostic steps ranked by failure probability.
    """

    __tablename__ = "diagnostic_flowcharts"

    symptom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    equipment_brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    equipment_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # split, package, mini-split, etc.
    category: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # cooling, heating, electrical, refrigerant, airflow
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Embedding for semantic matching of symptoms
    symptom_keywords: Mapped[Optional[list[str]]] = mapped_column(
        JSONB, nullable=True
    )  # e.g., ["compressor", "not starting", "won't run"]

    # Relationships
    steps: Mapped[list["DiagnosticStep"]] = relationship(
        "DiagnosticStep",
        back_populates="flowchart",
        cascade="all, delete-orphan",
        order_by="DiagnosticStep.priority_weight.desc()",
    )


class DiagnosticStep(Base, UUIDMixin, TimestampMixin):
    """A single diagnostic check within a flowchart.

    Ordered by priority_weight (higher = check first = more likely cause).
    """

    __tablename__ = "diagnostic_steps"

    flowchart_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_flowcharts.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_weight: Mapped[int] = mapped_column(
        Integer, default=50, nullable=False
    )  # 0-100, higher = check first

    check_description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    if_fail_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    if_pass_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    component: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # e.g., "capacitor", "contactor", "compressor"
    tools_needed: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    safety_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Feedback tracking
    times_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    times_corrected: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    flowchart: Mapped["DiagnosticFlowchart"] = relationship(
        "DiagnosticFlowchart",
        back_populates="steps",
    )


class TerminologyMapping(Base, UUIDMixin, TimestampMixin):
    """Maps textbook/manual terms to field-standard HVAC terminology.

    Example: "relay contacts" → "contactor"
    """

    __tablename__ = "terminology_mappings"

    textbook_term: Mapped[str] = mapped_column(String(255), nullable=False)
    field_term: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # e.g., "condenser_components", "electrical"
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # "seed", "technician_correction", "admin"
    confirmed_by_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FeedbackCorrection(Base, UUIDMixin, TimestampMixin):
    """Structured correction from a technician, either in-chat or via feedback UI."""

    __tablename__ = "feedback_corrections"

    message_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    correction_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # wrong_order, wrong_terminology, missing_step, additional_info
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correction_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )  # Structured correction details
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, applied, rejected
    applied_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Link to diagnostic flowchart if ordering correction
    flowchart_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("diagnostic_flowcharts.id", ondelete="SET NULL"),
        nullable=True,
    )
