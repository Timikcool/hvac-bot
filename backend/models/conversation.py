"""Conversation and message models for tracking."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UUIDMixin


class Conversation(Base, UUIDMixin, TimestampMixin):
    """Tracks a conversation session with equipment context."""

    __tablename__ = "conversations"

    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    equipment_brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    equipment_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    equipment_serial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    session_start: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
    )
    session_end: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    resolution_status: Mapped[str] = mapped_column(
        String(20),
        default="ongoing",
    )  # ongoing, resolved, escalated, abandoned
    user_satisfaction_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class Message(Base, UUIDMixin):
    """Individual message in a conversation."""

    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Assistant message fields
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # high, medium, low, none
    retrieval_scores: Mapped[Optional[list[float]]] = mapped_column(
        ARRAY(Float), nullable=True
    )
    cited_sources: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    safety_warnings: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), nullable=True)
    required_escalation: Mapped[bool] = mapped_column(Boolean, default=False)

    # User message fields
    contains_image: Mapped[bool] = mapped_column(Boolean, default=False)
    image_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # nameplate, problem, diagram
    detected_intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Diagnostic tracking
    diagnostic_flowchart_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("diagnostic_flowcharts.id", ondelete="SET NULL"),
        nullable=True,
    )
    terminology_corrections_applied: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Fine-tuning annotations
    is_good_example: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    annotation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    annotated_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    annotated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )
    retrievals: Mapped[list["MessageRetrieval"]] = relationship(
        "MessageRetrieval",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    feedback: Mapped[list["MessageFeedback"]] = relationship(
        "MessageFeedback",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageRetrieval(Base, UUIDMixin):
    """Tracks retrieved chunks for each assistant message."""

    __tablename__ = "message_retrievals"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    chunk_content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    rerank_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    was_used_in_response: Mapped[bool] = mapped_column(Boolean, default=True)
    position_in_results: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Relationships
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="retrievals",
    )


class MessageFeedback(Base, UUIDMixin):
    """User feedback on assistant responses."""

    __tablename__ = "message_feedback"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 1-5 star rating
    feedback_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # helpful, incorrect, incomplete, unclear, outdated
    feedback_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    missing_information: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correction_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # wrong_order, wrong_terminology, missing_step, good
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Relationships
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="feedback",
    )
