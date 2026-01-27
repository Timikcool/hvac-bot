"""Main RAG pipeline orchestrating all components."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.guardrails import ConfidenceLevel, ConfidenceScorer, ResponseValidator
from core.llm import LLMClient
from core.logging import get_logger
from services.rag.embedder import HVACEmbedder
from services.rag.generator import GeneratedResponse, GroundedGenerator
from services.rag.query_processor import ProcessedQuery, QueryProcessor
from services.rag.retriever import HVACRetriever
from services.rag.vector_store import HVACVectorStore

logger = get_logger("rag.pipeline")


@dataclass
class PipelineResponse:
    """Complete response from RAG pipeline."""

    answer: str
    confidence: ConfidenceLevel
    confidence_score: float
    citations: list[dict[str, Any]]
    safety_warnings: list[str]
    suggested_followups: list[str]
    requires_escalation: bool
    conversation_id: str
    message_id: str
    response_time_ms: int
    retrieval_scores: list[float]


class RAGPipeline:
    """Main RAG pipeline with integrated tracking.

    Orchestrates query processing, retrieval, generation, and validation.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        vector_store: HVACVectorStore | None = None,
        embedder: HVACEmbedder | None = None,
    ):
        # Initialize components
        self.llm = llm_client or LLMClient()
        self.vector_store = vector_store or HVACVectorStore()
        self.embedder = embedder or HVACEmbedder()

        # Build services
        self.query_processor = QueryProcessor(self.llm)
        self.retriever = HVACRetriever(self.vector_store, self.embedder)
        self.generator = GroundedGenerator(self.llm)
        self.validator = ResponseValidator(self.llm)
        self.confidence_scorer = ConfidenceScorer()

        # Tracker will be injected separately if needed
        self.tracker = None

    def set_tracker(self, tracker: Any) -> None:
        """Set conversation tracker for analytics."""
        self.tracker = tracker

    async def process_query(
        self,
        query: str,
        equipment_context: dict[str, Any],
        conversation_id: str | None = None,
        user_id: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        skip_validation: bool = False,
    ) -> PipelineResponse:
        """Process a query through the full RAG pipeline.

        Args:
            query: User query
            equipment_context: Equipment brand/model context
            conversation_id: Existing conversation ID (creates new if None)
            user_id: User ID for tracking
            conversation_history: Previous messages
            skip_validation: Skip response validation (faster but less safe)

        Returns:
            PipelineResponse with answer and metadata
        """
        start_time = time.time()
        message_id = str(uuid4())
        logger.info(f"PIPELINE | Starting query processing | query={query[:80]}...")
        logger.debug(f"PIPELINE | Equipment context: {equipment_context}")

        # Start/continue conversation tracking
        if not conversation_id:
            if self.tracker:
                conversation_id = await self.tracker.start_conversation(user_id, equipment_context)
                logger.info(f"PIPELINE | New conversation started | id={conversation_id}")
            else:
                conversation_id = str(uuid4())
                logger.info(f"PIPELINE | New conversation (no tracker) | id={conversation_id}")
        else:
            logger.debug(f"PIPELINE | Continuing conversation | id={conversation_id}")

        # Step 1: Process query
        logger.debug("PIPELINE | Step 1: Processing query...")
        processed_query = await self.query_processor.process(
            query,
            conversation_history,
        )
        logger.info(f"PIPELINE | Query processed | intent={processed_query.intent} | equipment_hints={processed_query.equipment_hints}")

        # Track user message
        if self.tracker:
            await self._track_user_message(
                conversation_id,
                query,
                processed_query,
            )

        # Step 2: Retrieve relevant chunks
        logger.debug("PIPELINE | Step 2: Retrieving relevant chunks...")
        retrieval_result = await self.retriever.retrieve(
            processed_query,
            equipment_context,
        )
        logger.info(
            f"PIPELINE | Retrieved {len(retrieval_result.chunks)} chunks | "
            f"total_found={retrieval_result.total_found} | strategy={retrieval_result.retrieval_strategy}"
        )
        if retrieval_result.chunks:
            scores = [c["score"] for c in retrieval_result.chunks]
            logger.debug(f"PIPELINE | Retrieval scores: min={min(scores):.3f} max={max(scores):.3f} avg={sum(scores)/len(scores):.3f}")

        # Step 3: Generate response
        logger.debug("PIPELINE | Step 3: Generating response...")
        response = await self.generator.generate(
            query=query,
            retrieved_chunks=retrieval_result.chunks,
            equipment_context=equipment_context,
            conversation_history=conversation_history,
        )
        logger.info(f"PIPELINE | Response generated | confidence={response.confidence.value} | citations={len(response.citations)}")

        # Step 4: Validate response (optional)
        final_answer = response.answer
        validation_result = None

        if not skip_validation and retrieval_result.chunks:
            logger.debug("PIPELINE | Step 4: Validating response...")
            validation_result = await self.validator.validate(
                response.answer,
                retrieval_result.chunks,
                query,
            )
            logger.debug(f"PIPELINE | Validation complete | is_valid={validation_result.is_valid} | violations={len(validation_result.violations)}")
            if validation_result.corrected_response:
                logger.info("PIPELINE | Response was corrected by validator")
                final_answer = validation_result.corrected_response
        else:
            logger.debug("PIPELINE | Step 4: Skipping validation")

        # Step 5: Calculate final confidence
        logger.debug("PIPELINE | Step 5: Calculating confidence...")
        retrieval_scores = [c["score"] for c in retrieval_result.chunks]

        if validation_result:
            confidence_score, confidence_level = self.confidence_scorer.calculate_score(
                final_answer,
                retrieval_scores,
                validation_result,
                processed_query.intent,
            )
        else:
            confidence_score = sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else 0
            confidence_level = response.confidence

        response_time_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"PIPELINE | Complete | confidence={confidence_level.value} ({confidence_score:.3f}) | "
            f"escalation={response.requires_escalation or confidence_level == ConfidenceLevel.LOW} | "
            f"time={response_time_ms}ms"
        )

        # Track assistant message
        if self.tracker:
            await self._track_assistant_message(
                conversation_id,
                message_id,
                final_answer,
                confidence_score,
                confidence_level,
                retrieval_result.chunks,
                response.citations,
                response.safety_warnings,
                response.requires_escalation,
                response_time_ms,
            )

        return PipelineResponse(
            answer=final_answer,
            confidence=confidence_level,
            confidence_score=confidence_score,
            citations=response.citations,
            safety_warnings=response.safety_warnings,
            suggested_followups=response.suggested_followups,
            requires_escalation=response.requires_escalation or confidence_level == ConfidenceLevel.LOW,
            conversation_id=conversation_id,
            message_id=message_id,
            response_time_ms=response_time_ms,
            retrieval_scores=retrieval_scores,
        )

    async def _track_user_message(
        self,
        conversation_id: str,
        content: str,
        processed_query: ProcessedQuery,
    ) -> None:
        """Track user message if tracker is available."""
        if not self.tracker:
            return

        from services.tracking.conversation_tracker import TrackedMessage

        message = TrackedMessage(
            id=str(uuid4()),
            role="user",
            content=content,
            created_at=datetime.utcnow(),
            detected_intent=processed_query.intent,
        )

        await self.tracker.track_message(conversation_id, message)

    async def _track_assistant_message(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        confidence_score: float,
        confidence_level: ConfidenceLevel,
        chunks: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        safety_warnings: list[str],
        requires_escalation: bool,
        response_time_ms: int,
    ) -> None:
        """Track assistant message with retrievals if tracker is available."""
        if not self.tracker:
            return

        from services.tracking.conversation_tracker import TrackedMessage, TrackedRetrieval

        message = TrackedMessage(
            id=message_id,
            role="assistant",
            content=content,
            created_at=datetime.utcnow(),
            confidence_score=confidence_score,
            confidence_level=confidence_level.value,
            retrieval_scores=[c["score"] for c in chunks],
            cited_sources=citations,
            safety_warnings=safety_warnings,
            required_escalation=requires_escalation,
            response_time_ms=response_time_ms,
        )

        retrievals = [
            TrackedRetrieval(
                chunk_id=chunk.get("id", str(uuid4())),
                chunk_content=chunk["content"],
                chunk_metadata=chunk.get("metadata", {}),
                similarity_score=chunk["score"],
                was_used_in_response=True,
                position_in_results=i,
            )
            for i, chunk in enumerate(chunks)
        ]

        await self.tracker.track_message(conversation_id, message, retrievals)
