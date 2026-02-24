"""OpenClaw webhook endpoints for cross-platform messaging."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from api.dependencies import get_db, get_rag_pipeline, get_tracker
from core.logging import get_logger
from services.openclaw.user_sync import UserSync
from services.rag.pipeline import RAGPipeline
from services.tracking.conversation_tracker import ConversationTracker

logger = get_logger("api.openclaw")
router = APIRouter(prefix="/openclaw", tags=["openclaw"])

SHARED_SECRET = os.environ.get("OPENCLAW_SHARED_SECRET", "")


# --- Auth ---

def verify_openclaw_secret(
    x_openclaw_secret: str = Header(None),
) -> None:
    """Verify shared secret from OpenClaw gateway."""
    if not SHARED_SECRET:
        logger.warning("OPENCLAW | No shared secret configured, skipping auth")
        return
    if x_openclaw_secret != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid OpenClaw secret")


# --- Request/Response Models ---

class OpenClawChatRequest(BaseModel):
    """Chat message from OpenClaw gateway."""

    message: str
    platform: str  # "telegram" or "whatsapp"
    platform_user_id: str
    user_name: str | None = None
    conversation_id: str | None = None
    equipment: dict[str, Any] | None = None
    image_data: str | None = None  # base64 encoded, if sending an image


class OpenClawChatResponse(BaseModel):
    """Response back to OpenClaw gateway."""

    answer: str
    confidence: str
    citations: list[dict[str, Any]]
    safety_warnings: list[str]
    suggested_followups: list[str]
    requires_escalation: bool
    conversation_id: str
    message_id: str
    user_id: str


class OpenClawSyncRequest(BaseModel):
    """Memory/preference sync from OpenClaw."""

    platform: str
    platform_user_id: str
    preferences: dict[str, Any]


# --- Routes ---

@router.post("/chat", response_model=OpenClawChatResponse)
async def openclaw_chat(
    request: OpenClawChatRequest,
    pipeline: RAGPipeline = Depends(get_rag_pipeline),
    tracker: ConversationTracker = Depends(get_tracker),
    db=Depends(get_db),
    _auth: None = Depends(verify_openclaw_secret),
) -> OpenClawChatResponse:
    """Receive messages from OpenClaw gateway.

    Resolves user identity, processes through RAG pipeline,
    and returns formatted response.
    """
    logger.info(
        f"OPENCLAW | Chat from {request.platform} | "
        f"user={request.platform_user_id} | msg={request.message[:80]}..."
    )

    try:
        # Resolve user identity
        user_sync = UserSync(db)
        user = await user_sync.get_or_create_user(
            platform=request.platform,
            platform_id=request.platform_user_id,
            name=request.user_name,
        )

        # Set tracker on pipeline
        pipeline.set_tracker(tracker)

        # Build equipment context
        equipment_context = request.equipment or {}

        # Process through RAG pipeline
        result = await pipeline.process_query(
            query=request.message,
            equipment_context=equipment_context,
            conversation_id=request.conversation_id,
            user_id=user.id,
        )

        logger.info(
            f"OPENCLAW | Response generated | user={user.id} | "
            f"confidence={result.confidence.value} | time={result.response_time_ms}ms"
        )

        return OpenClawChatResponse(
            answer=result.answer,
            confidence=result.confidence.value,
            citations=result.citations,
            safety_warnings=result.safety_warnings,
            suggested_followups=result.suggested_followups,
            requires_escalation=result.requires_escalation,
            conversation_id=result.conversation_id,
            message_id=result.message_id,
            user_id=user.id,
        )

    except Exception as e:
        logger.error(f"OPENCLAW | Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def openclaw_sync(
    request: OpenClawSyncRequest,
    db=Depends(get_db),
    _auth: None = Depends(verify_openclaw_secret),
) -> dict[str, str]:
    """Receive memory/preference updates from OpenClaw.

    Syncs user preferences (preferred brands, experience level, etc.)
    from OpenClaw's persistent memory to the backend database.
    """
    logger.info(
        f"OPENCLAW | Sync from {request.platform} | "
        f"user={request.platform_user_id} | keys={list(request.preferences.keys())}"
    )

    try:
        user_sync = UserSync(db)
        user = await user_sync.get_or_create_user(
            platform=request.platform,
            platform_id=request.platform_user_id,
        )

        await user_sync.sync_preferences(
            user_id=user.id,
            preferences=request.preferences,
        )

        return {"status": "synced", "user_id": user.id}

    except Exception as e:
        logger.error(f"OPENCLAW | Sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def openclaw_health() -> dict[str, str]:
    """Health check for OpenClaw integration."""
    return {"status": "healthy", "service": "openclaw-webhook"}
