"""A/B testing experiment models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class Experiment(Base, UUIDMixin):
    """A/B test experiment configuration."""

    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variants: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )  # variant_name -> config
    traffic_allocation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )  # variant_name -> percentage
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ExperimentExposure(Base, UUIDMixin):
    """Records when a user is exposed to an experiment variant."""

    __tablename__ = "experiment_exposures"

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    exposed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class ExperimentOutcome(Base, UUIDMixin):
    """Records outcome metrics for experiment analysis."""

    __tablename__ = "experiment_outcomes"

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
