"""User identity sync between OpenClaw and HVAC backend."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from models.user import User

logger = get_logger("openclaw.user_sync")


class UserSync:
    """Map OpenClaw platform users to internal HVAC User records.

    Handles Telegram/WhatsApp identity resolution and preference sync.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_or_create_user(
        self,
        platform: str,
        platform_id: str,
        name: str | None = None,
    ) -> User:
        """Find existing user by platform ID or create a new one.

        Args:
            platform: "telegram" or "whatsapp"
            platform_id: Platform-specific user ID
            name: User's display name (optional)

        Returns:
            User model instance
        """
        # Look up by platform ID
        user = await self._find_by_platform(platform, platform_id)

        if user:
            # Update last active
            user.last_active_at = datetime.utcnow()
            if name and not user.name:
                user.name = name
            await self.db.commit()
            logger.debug(f"USER_SYNC | Found existing user | id={user.id} | platform={platform}")
            return user

        # Create new user
        user = User(
            name=name,
            platform_source=platform,
            is_active=True,
            last_active_at=datetime.utcnow(),
        )

        if platform == "telegram":
            user.telegram_id = platform_id
        elif platform == "whatsapp":
            user.whatsapp_id = platform_id

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"USER_SYNC | Created new user | id={user.id} | platform={platform} | name={name}")
        return user

    async def sync_preferences(
        self,
        user_id: str,
        preferences: dict[str, Any],
    ) -> None:
        """Update user preferences from OpenClaw memory.

        Args:
            user_id: Internal user ID
            preferences: Dict with keys like preferred_brands, experience_level, etc.
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"USER_SYNC | User not found for preference sync | id={user_id}")
            return

        if preferences.get("preferred_brands"):
            brands = preferences["preferred_brands"]
            if isinstance(brands, list):
                brands = ",".join(brands)
            user.preferred_brands = brands

        if preferences.get("experience_level"):
            user.experience_level = preferences["experience_level"]

        if preferences.get("name") and not user.name:
            user.name = preferences["name"]

        if preferences.get("company"):
            user.company = preferences["company"]

        await self.db.commit()
        logger.info(f"USER_SYNC | Preferences updated | user={user_id} | keys={list(preferences.keys())}")

    async def link_platforms(
        self,
        user_id: str,
        platform: str,
        platform_id: str,
    ) -> bool:
        """Link an additional platform account to an existing user.

        Useful when a tech uses both Telegram and WhatsApp.
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        if platform == "telegram":
            user.telegram_id = platform_id
        elif platform == "whatsapp":
            user.whatsapp_id = platform_id

        await self.db.commit()
        logger.info(f"USER_SYNC | Linked {platform} to user {user_id}")
        return True

    async def _find_by_platform(
        self,
        platform: str,
        platform_id: str,
    ) -> User | None:
        """Find user by platform-specific ID."""
        if platform == "telegram":
            result = await self.db.execute(
                select(User).where(User.telegram_id == platform_id)
            )
        elif platform == "whatsapp":
            result = await self.db.execute(
                select(User).where(User.whatsapp_id == platform_id)
            )
        else:
            return None

        return result.scalar_one_or_none()
