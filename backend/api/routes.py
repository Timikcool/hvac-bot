"""Main API routes for chat, image analysis, and equipment."""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.dependencies import (
    get_nameplate_reader,
    get_problem_analyzer,
    get_rag_pipeline,
    get_tracker,
)
from core.logging import get_logger
from services.rag.pipeline import RAGPipeline
from services.tracking.conversation_tracker import ConversationTracker
from services.vision.nameplate_reader import NameplateReader
from services.vision.problem_analyzer import ProblemAnalyzer

logger = get_logger("api.routes")
router = APIRouter(tags=["chat"])


# Request/Response Models
class EquipmentContext(BaseModel):
    """Equipment context for queries."""

    brand: str | None = None
    model: str | None = None
    serial: str | None = None
    system_type: str | None = None


class ChatRequest(BaseModel):
    """Chat request payload."""

    message: str
    equipment: EquipmentContext | None = None
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    """Chat response payload."""

    answer: str
    confidence: str
    confidence_score: float
    citations: list[dict[str, Any]]
    safety_warnings: list[str]
    suggested_followups: list[str]
    requires_escalation: bool
    conversation_id: str
    message_id: str
    response_time_ms: int


class EquipmentScanResponse(BaseModel):
    """Equipment scan response."""

    brand: str
    model: str
    serial: str
    manufacture_date: str
    specs: dict[str, Any]
    equipment_type: str
    confidence: float


class DiagnosisResponse(BaseModel):
    """Visual diagnosis response."""

    identified_components: list[str]
    visible_issues: list[dict[str, Any]]
    suggested_causes: list[str]
    recommended_checks: list[str]
    manual_references: list[dict[str, Any]]
    confidence: float
    requires_physical_inspection: bool
    safety_concerns: list[str]


class FeedbackRequest(BaseModel):
    """Feedback request payload."""

    message_id: str
    rating: int | None = None  # 1-5 star rating
    feedback_type: str | None = None  # helpful, incorrect, incomplete, unclear, outdated
    details: str | None = None
    correct_answer: str | None = None


# Routes
@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    pipeline: RAGPipeline = Depends(get_rag_pipeline),
    tracker: ConversationTracker = Depends(get_tracker),
) -> ChatResponse:
    """Main chat endpoint for HVAC questions.

    Supports text queries with optional equipment context.
    """
    logger.info(f"CHAT | Received message: {request.message[:100]}...")
    logger.debug(f"CHAT | Equipment context: {request.equipment}")
    logger.debug(f"CHAT | Conversation ID: {request.conversation_id}")

    try:
        # Set tracker on pipeline
        logger.debug("CHAT | Setting tracker on pipeline")
        pipeline.set_tracker(tracker)

        # Build equipment context
        equipment_context = {}
        if request.equipment:
            equipment_context = request.equipment.model_dump(exclude_none=True)
            logger.info(f"CHAT | Equipment: {equipment_context}")

        # Process query
        logger.info("CHAT | Processing query through RAG pipeline...")
        result = await pipeline.process_query(
            query=request.message,
            equipment_context=equipment_context,
            conversation_id=request.conversation_id,
        )

        logger.info(
            f"CHAT | Response generated | confidence={result.confidence.value} "
            f"| citations={len(result.citations)} | time={result.response_time_ms}ms"
        )

        return ChatResponse(
            answer=result.answer,
            confidence=result.confidence.value,
            confidence_score=result.confidence_score,
            citations=result.citations,
            safety_warnings=result.safety_warnings,
            suggested_followups=result.suggested_followups,
            requires_escalation=result.requires_escalation,
            conversation_id=result.conversation_id,
            message_id=result.message_id,
            response_time_ms=result.response_time_ms,
        )

    except Exception as e:
        logger.error(f"CHAT | Error processing request: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan-equipment", response_model=EquipmentScanResponse)
async def scan_equipment(
    image: UploadFile = File(...),
    reader: NameplateReader = Depends(get_nameplate_reader),
) -> EquipmentScanResponse:
    """Scan equipment nameplate to identify unit.

    Returns equipment info and available manuals.
    """
    try:
        # Validate file type
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        image_bytes = await image.read()

        # Limit file size (10MB)
        if len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

        identification = await reader.read_nameplate(image_bytes)

        return EquipmentScanResponse(
            brand=identification.brand,
            model=identification.model,
            serial=identification.serial,
            manufacture_date=identification.manufacture_date,
            specs=identification.specs,
            equipment_type=identification.equipment_type,
            confidence=identification.confidence,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-image", response_model=DiagnosisResponse)
async def analyze_problem_image(
    image: UploadFile = File(...),
    description: str = Form(...),
    equipment_brand: str | None = Form(None),
    equipment_model: str | None = Form(None),
    analyzer: ProblemAnalyzer = Depends(get_problem_analyzer),
) -> DiagnosisResponse:
    """Analyze photo of equipment for visible issues.

    Cross-references with manuals for equipment-specific guidance.
    """
    try:
        # Validate file type
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        image_bytes = await image.read()

        # Limit file size (10MB)
        if len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

        equipment_context = {
            "brand": equipment_brand,
            "model": equipment_model,
        }

        diagnosis = await analyzer.analyze_problem_image(
            image_data=image_bytes,
            user_description=description,
            equipment_context=equipment_context,
        )

        return DiagnosisResponse(
            identified_components=diagnosis.identified_components,
            visible_issues=[
                {
                    "description": issue.description,
                    "evidence": issue.evidence,
                    "severity": issue.severity,
                }
                for issue in diagnosis.visible_issues
            ],
            suggested_causes=diagnosis.suggested_causes,
            recommended_checks=diagnosis.recommended_checks,
            manual_references=diagnosis.manual_references,
            confidence=diagnosis.confidence,
            requires_physical_inspection=diagnosis.requires_physical_inspection,
            safety_concerns=diagnosis.safety_concerns,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    tracker: ConversationTracker = Depends(get_tracker),
) -> dict[str, Any]:
    """Submit feedback on AI response quality.

    Supports:
    - Star rating (1-5)
    - Feedback type (helpful, incorrect, incomplete, unclear, outdated)
    - Free-text details
    """
    try:
        # Validate rating if provided
        if request.rating is not None:
            if not 1 <= request.rating <= 5:
                raise HTTPException(
                    status_code=400,
                    detail="Rating must be between 1 and 5",
                )
        
        # Validate feedback type if provided
        valid_types = ["helpful", "incorrect", "incomplete", "unclear", "outdated", None]
        if request.feedback_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid feedback type. Must be one of: {valid_types[:-1]}",
            )

        feedback_id = await tracker.track_feedback(
            message_id=request.message_id,
            feedback_type=request.feedback_type,
            rating=request.rating,
            details=request.details,
            correct_answer=request.correct_answer,
        )
        
        logger.info(f"FEEDBACK | message={request.message_id} | rating={request.rating} | type={request.feedback_type}")

        return {
            "status": "recorded", 
            "feedback_id": feedback_id,
            "rating": request.rating,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FEEDBACK | Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/end")
async def end_conversation(
    conversation_id: str,
    resolution_status: str = Form(...),
    satisfaction_score: int | None = Form(None),
    tracker: ConversationTracker = Depends(get_tracker),
) -> dict[str, str]:
    """Mark conversation as ended with resolution status."""
    try:
        valid_statuses = ["resolved", "escalated", "abandoned"]
        if resolution_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}",
            )

        if satisfaction_score is not None and not 1 <= satisfaction_score <= 5:
            raise HTTPException(
                status_code=400,
                detail="Satisfaction score must be between 1 and 5",
            )

        await tracker.end_conversation(
            conversation_id=conversation_id,
            resolution_status=resolution_status,
            satisfaction_score=satisfaction_score,
        )

        return {"status": "ended", "conversation_id": conversation_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
