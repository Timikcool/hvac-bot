"""Analytics and knowledge gap models."""

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Date, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class RetrievalQualityMetric(Base, UUIDMixin):
    """Aggregated RAG quality metrics per day/equipment."""

    __tablename__ = "retrieval_quality_metrics"

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    equipment_brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    equipment_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    query_intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Metrics
    total_queries: Mapped[int] = mapped_column(Integer, default=0)
    avg_top_retrieval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_response_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    queries_with_no_results: Mapped[int] = mapped_column(Integer, default=0)
    queries_requiring_escalation: Mapped[int] = mapped_column(Integer, default=0)
    positive_feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_feedback_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # Unique constraint for aggregation key
        {"sqlite_autoincrement": True},
    )


class KnowledgeGap(Base, UUIDMixin, TimestampMixin):
    """Identified knowledge gaps from low-confidence queries."""

    __tablename__ = "knowledge_gaps"

    query_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    equipment_brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    equipment_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    sample_queries: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    avg_retrieval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="identified", index=True
    )  # identified, in_progress, resolved
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
