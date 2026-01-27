"""Unified RAG abstraction supporting multiple backends.

Provides a single interface for RAG operations using:
- Custom RAG Pipeline (default) - Full control, uses embedder + retriever + generator
- Vertex AI RAG Engine (managed) - Fully managed by Google

Provider selection is based on configuration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config import get_settings
from core.guardrails import ConfidenceLevel
from core.logging import get_logger

logger = get_logger("rag.unified")


class RAGProvider(Enum):
    """RAG provider options."""
    CUSTOM = "custom"
    VERTEX = "vertex"


@dataclass
class UnifiedRAGResponse:
    """Unified response from RAG system."""
    
    answer: str
    confidence: ConfidenceLevel
    confidence_score: float
    sources: list[dict[str, Any]] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    suggested_followups: list[str] = field(default_factory=list)
    requires_escalation: bool = False
    conversation_id: str = ""
    message_id: str = ""
    response_time_ms: int = 0
    provider: RAGProvider = RAGProvider.CUSTOM
    model: str = ""


class UnifiedRAG:
    """Unified RAG interface supporting multiple backends.
    
    Automatically selects the appropriate backend based on configuration:
    - custom: Uses custom RAG pipeline with embedder + retriever + generator
    - vertex: Uses Vertex AI RAG Engine for fully managed RAG
    
    Usage:
        rag = UnifiedRAG()
        response = await rag.query("How do I reset error code E01?", equipment_context)
    """
    
    def __init__(self, force_provider: RAGProvider | None = None):
        """Initialize unified RAG system.
        
        Args:
            force_provider: Force a specific provider (overrides config)
        """
        settings = get_settings()
        
        self._provider: RAGProvider
        self._custom_pipeline = None
        self._vertex_engine = None
        
        # Determine provider
        if force_provider:
            self._provider = force_provider
        else:
            provider_config = settings.rag_provider
            if provider_config == "vertex":
                self._provider = RAGProvider.VERTEX
            else:
                self._provider = RAGProvider.CUSTOM
        
        logger.info(f"UNIFIED RAG | Initialized | provider={self._provider.value}")
    
    @property
    def provider(self) -> RAGProvider:
        """Get active provider."""
        return self._provider
    
    @property
    def custom_pipeline(self):
        """Lazy-load custom RAG pipeline."""
        if self._custom_pipeline is None:
            from services.rag.pipeline import RAGPipeline
            self._custom_pipeline = RAGPipeline()
        return self._custom_pipeline
    
    @property
    def vertex_engine(self):
        """Lazy-load Vertex AI RAG Engine."""
        if self._vertex_engine is None:
            from services.gcp.rag_engine import VertexRAGEngine
            self._vertex_engine = VertexRAGEngine()
        return self._vertex_engine
    
    def set_tracker(self, tracker: Any) -> None:
        """Set conversation tracker (only for custom pipeline)."""
        if self._provider == RAGProvider.CUSTOM:
            self.custom_pipeline.set_tracker(tracker)
    
    async def query(
        self,
        query: str,
        equipment_context: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> UnifiedRAGResponse:
        """Process a query through the RAG system.
        
        Args:
            query: User query
            equipment_context: Equipment brand/model context
            conversation_id: Existing conversation ID
            user_id: User ID for tracking
            conversation_history: Previous messages
            
        Returns:
            UnifiedRAGResponse with answer and metadata
        """
        equipment_context = equipment_context or {}
        
        if self._provider == RAGProvider.VERTEX:
            return await self._query_vertex(query, equipment_context)
        else:
            return await self._query_custom(
                query, equipment_context, conversation_id, user_id, conversation_history
            )
    
    async def _query_custom(
        self,
        query: str,
        equipment_context: dict[str, Any],
        conversation_id: str | None,
        user_id: str | None,
        conversation_history: list[dict[str, Any]] | None,
    ) -> UnifiedRAGResponse:
        """Query using custom RAG pipeline."""
        from services.rag.pipeline import RAGPipeline
        
        response = await self.custom_pipeline.process_query(
            query=query,
            equipment_context=equipment_context,
            conversation_id=conversation_id,
            user_id=user_id,
            conversation_history=conversation_history,
        )
        
        return UnifiedRAGResponse(
            answer=response.answer,
            confidence=response.confidence,
            confidence_score=response.confidence_score,
            sources=response.citations,
            safety_warnings=response.safety_warnings,
            suggested_followups=response.suggested_followups,
            requires_escalation=response.requires_escalation,
            conversation_id=response.conversation_id,
            message_id=response.message_id,
            response_time_ms=response.response_time_ms,
            provider=RAGProvider.CUSTOM,
            model="claude-3-5-sonnet",
        )
    
    async def _query_vertex(
        self,
        query: str,
        equipment_context: dict[str, Any],
    ) -> UnifiedRAGResponse:
        """Query using Vertex AI RAG Engine."""
        import time
        from uuid import uuid4
        
        start_time = time.time()
        
        # Enhance query with equipment context
        enhanced_query = query
        if equipment_context.get("brand") or equipment_context.get("model"):
            context_parts = []
            if equipment_context.get("brand"):
                context_parts.append(f"Brand: {equipment_context['brand']}")
            if equipment_context.get("model"):
                context_parts.append(f"Model: {equipment_context['model']}")
            enhanced_query = f"{' | '.join(context_parts)}\n\nQuestion: {query}"
        
        try:
            response = await self.vertex_engine.query(
                question=enhanced_query,
                top_k=10,
            )
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Convert sources to citation format
            sources = [
                {
                    "content": s.get("content", ""),
                    "source": s.get("source", ""),
                }
                for s in response.sources
            ]
            
            # Estimate confidence based on source count
            confidence_score = min(0.9, 0.5 + (len(sources) * 0.1))
            if confidence_score >= 0.8:
                confidence = ConfidenceLevel.HIGH
            elif confidence_score >= 0.5:
                confidence = ConfidenceLevel.MEDIUM
            else:
                confidence = ConfidenceLevel.LOW
            
            return UnifiedRAGResponse(
                answer=response.answer,
                confidence=confidence,
                confidence_score=confidence_score,
                sources=sources,
                safety_warnings=[],
                suggested_followups=[],
                requires_escalation=confidence == ConfidenceLevel.LOW,
                conversation_id=str(uuid4()),
                message_id=str(uuid4()),
                response_time_ms=response_time_ms,
                provider=RAGProvider.VERTEX,
                model=response.model,
            )
            
        except Exception as e:
            logger.error(f"UNIFIED RAG | Vertex query failed: {e}")
            # Fallback to custom pipeline
            logger.warning("UNIFIED RAG | Falling back to custom pipeline")
            self._provider = RAGProvider.CUSTOM
            return await self._query_custom(query, equipment_context, None, None, None)
    
    async def retrieve_only(
        self,
        query: str,
        equipment_context: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant chunks without generation.
        
        Useful for debugging or custom generation.
        
        Args:
            query: Search query
            equipment_context: Equipment context
            top_k: Number of chunks to retrieve
            
        Returns:
            List of retrieved chunks
        """
        equipment_context = equipment_context or {}
        
        if self._provider == RAGProvider.VERTEX:
            chunks = await self.vertex_engine.retrieve_only(
                query=query,
                top_k=top_k,
            )
            return chunks
        else:
            # Use custom retriever
            from services.rag.query_processor import QueryProcessor
            
            # Process query first
            query_processor = QueryProcessor(self.custom_pipeline.llm)
            processed = await query_processor.process(query)
            
            # Retrieve
            result = await self.custom_pipeline.retriever.retrieve(
                processed,
                equipment_context,
            )
            
            return result.chunks
    
    async def ingest_document(
        self,
        file_path: str,
        metadata: dict[str, Any],
    ) -> str:
        """Ingest a document into the RAG system.
        
        For Vertex AI, uses RAG Engine's built-in ingestion.
        For custom, uses the standard ingestion pipeline.
        
        Args:
            file_path: Path to document
            metadata: Document metadata
            
        Returns:
            Document ID
        """
        if self._provider == RAGProvider.VERTEX:
            return await self.vertex_engine.ingest_document(
                file_path=file_path,
                display_name=metadata.get("title", ""),
                description=metadata.get("description", ""),
                metadata=metadata,
            )
        else:
            # For custom pipeline, ingestion is handled separately
            # via the admin API endpoints
            raise NotImplementedError(
                "Use /api/admin/documents/upload for custom pipeline ingestion"
            )


