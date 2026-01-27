"""User models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """Application user (technician)."""

    __tablename__ = "users"

    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Auth
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )  # For SSO
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Preferences
    preferred_brands: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class AdminUser(Base, UUIDMixin, TimestampMixin):
    """Admin user for internal dashboard."""

    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="analyst")  # analyst, admin, superadmin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
