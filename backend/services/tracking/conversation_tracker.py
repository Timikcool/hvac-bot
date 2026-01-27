"""Conversation tracking for analytics and fine-tuning."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation, Message, MessageFeedback, MessageRetrieval


@dataclass
class TrackedMessage:
    """Message data for tracking."""

    id: str
    role: str
    content: str
    created_at: datetime

    # Assistant-specific
    confidence_score: float | None = None
    confidence_level: str | None = None
    retrieval_scores: list[float] = field(default_factory=list)
    cited_sources: list[dict[str, Any]] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    required_escalation: bool = False
    response_time_ms: int | None = None

    # User-specific
    contains_image: bool = False
    image_type: str | None = None
    detected_intent: str | None = None


@dataclass
class TrackedRetrieval:
    """Retrieval data for tracking."""

    chunk_id: str
    chunk_content: str
    chunk_metadata: dict[str, Any]
    similarity_score: float
    rerank_score: float | None = None
    was_used_in_response: bool = True
    position_in_results: int = 0


class ConversationTracker:
    """Tracks all conversations and messages for analytics and fine-tuning.

    Designed for minimal latency impact on main chat flow.
    """

    def __init__(self, db_session: AsyncSession, redis_client: Redis | None = None):
        self.db = db_session
        self.redis = redis_client

    async def start_conversation(
        self,
        user_id: str | None,
        equipment_context: dict[str, Any],
    ) -> str:
        """Initialize a new conversation tracking session.

        Args:
            user_id: Optional user ID
            equipment_context: Equipment brand/model context

        Returns:
            New conversation ID
        """
        conversation_id = str(uuid4())

        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            equipment_brand=equipment_context.get("brand"),
            equipment_model=equipment_context.get("model"),
            equipment_serial=equipment_context.get("serial"),
            system_type=equipment_context.get("system_type"),
            metadata=equipment_context,
        )

        self.db.add(conversation)
        await self.db.commit()

        # Update real-time metrics
        if self.redis:
            await self.redis.incr("stats:conversations:today")
            if equipment_context.get("brand"):
                await self.redis.hincrby(
                    "stats:conversations:by_brand",
                    equipment_context["brand"],
                    1,
                )

        return conversation_id

    async def track_message(
        self,
        conversation_id: str,
        message: TrackedMessage,
        retrievals: list[TrackedRetrieval] | None = None,
    ) -> str:
        """Track a single message with optional retrieval data.

        Args:
            conversation_id: Conversation ID
            message: Message data
            retrievals: Optional retrieval data

        Returns:
            Message ID
        """
        message_id = message.id or str(uuid4())

        # Insert message
        msg_record = Message(
            id=message_id,
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_level=message.confidence_level,
            retrieval_scores=message.retrieval_scores or None,
            cited_sources=message.cited_sources if message.cited_sources else None,
            safety_warnings=message.safety_warnings or None,
            required_escalation=message.required_escalation,
            contains_image=message.contains_image,
            image_type=message.image_type,
            detected_intent=message.detected_intent,
            response_time_ms=message.response_time_ms,
            created_at=message.created_at,
        )

        self.db.add(msg_record)

        # Insert retrieval data
        if retrievals:
            for i, ret in enumerate(retrievals):
                retrieval_record = MessageRetrieval(
                    id=str(uuid4()),
                    message_id=message_id,
                    chunk_id=ret.chunk_id,
                    chunk_content=ret.chunk_content,
                    chunk_metadata=ret.chunk_metadata,
                    similarity_score=ret.similarity_score,
                    rerank_score=ret.rerank_score,
                    was_used_in_response=ret.was_used_in_response,
                    position_in_results=i,
                )
                self.db.add(retrieval_record)

        # Update conversation message count
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(total_messages=Conversation.total_messages + 1)
        )

        await self.db.commit()

        # Real-time metrics
        if self.redis and message.role == "assistant":
            await self._update_realtime_metrics(message)

        return message_id

    async def track_feedback(
        self,
        message_id: str,
        feedback_type: str | None = None,
        rating: int | None = None,
        details: str | None = None,
        correct_answer: str | None = None,
    ) -> str:
        """Track user feedback on a response.

        Args:
            message_id: Message ID
            feedback_type: Type (helpful, incorrect, incomplete, unclear, outdated)
            rating: Star rating 1-5
            details: Optional details
            correct_answer: User-provided correct answer

        Returns:
            Feedback ID
        """
        feedback_id = str(uuid4())

        feedback = MessageFeedback(
            id=feedback_id,
            message_id=message_id,
            feedback_type=feedback_type,
            rating=rating,
            feedback_details=details,
            correct_answer=correct_answer,
        )

        self.db.add(feedback)
        await self.db.commit()

        # Update metrics
        if self.redis:
            if feedback_type:
                await self.redis.hincrby("stats:feedback:by_type", feedback_type, 1)
            if rating:
                await self.redis.hincrby("stats:feedback:by_rating", str(rating), 1)
                # Track average rating
                await self.redis.incrbyfloat("stats:feedback:rating_sum", rating)
                await self.redis.incr("stats:feedback:rating_count")

        # Auto-flag for review if negative feedback
        if feedback_type in ["incorrect", "outdated"] or (rating and rating <= 2):
            await self._flag_for_review(message_id, feedback_type or f"low_rating_{rating}")

        return feedback_id

    async def end_conversation(
        self,
        conversation_id: str,
        resolution_status: str,
        satisfaction_score: int | None = None,
    ) -> None:
        """Mark conversation as ended with resolution status.

        Args:
            conversation_id: Conversation ID
            resolution_status: Status (resolved, escalated, abandoned)
            satisfaction_score: Optional 1-5 rating
        """
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                session_end=datetime.utcnow(),
                resolution_status=resolution_status,
                user_satisfaction_score=satisfaction_score,
            )
        )
        await self.db.commit()

    async def _update_realtime_metrics(self, message: TrackedMessage) -> None:
        """Update real-time metrics in Redis."""
        if not self.redis:
            return

        pipe = self.redis.pipeline()

        # Confidence distribution
        if message.confidence_level:
            pipe.hincrby("stats:confidence:distribution", message.confidence_level, 1)

        # Response time histogram
        if message.response_time_ms:
            bucket = self._get_latency_bucket(message.response_time_ms)
            pipe.hincrby("stats:latency:histogram", bucket, 1)

        # Escalation rate
        if message.required_escalation:
            pipe.incr("stats:escalations:today")

        await pipe.execute()

    async def _flag_for_review(self, message_id: str, reason: str) -> None:
        """Flag a message for manual review."""
        if not self.redis:
            return

        await self.redis.sadd("review:flagged_messages", message_id)
        await self.redis.hset(f"review:message:{message_id}", "reason", reason)

    @staticmethod
    def _get_latency_bucket(ms: int) -> str:
        """Get latency bucket for histogram."""
        if ms < 500:
            return "<500ms"
        elif ms < 1000:
            return "500ms-1s"
        elif ms < 2000:
            return "1s-2s"
        elif ms < 5000:
            return "2s-5s"
        else:
            return ">5s"
