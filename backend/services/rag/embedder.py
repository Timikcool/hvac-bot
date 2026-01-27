"""Embedding service for HVAC content.

Supports multiple providers:
- Vertex AI (text-embedding-004) - 768 dimensions
- OpenAI (text-embedding-3-small) - 1536 dimensions

Provider selection is automatic based on configuration.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from openai import AsyncOpenAI

from config import get_settings
from core.logging import get_logger

logger = get_logger("rag.embedder")


class EmbeddingProvider(Enum):
    """Embedding provider options."""
    OPENAI = "openai"
    VERTEX = "vertex"
    GEMINI = "gemini"  # Uses API key (simpler than Vertex)


@dataclass
class EmbeddingResult:
    """Result of embedding operation."""

    embeddings: list[list[float]]
    model: str
    provider: EmbeddingProvider
    dimension: int
    usage: dict[str, int] | None = None


# Dimension constants for each provider
OPENAI_EMBEDDING_DIM = 1536  # text-embedding-3-small
VERTEX_EMBEDDING_DIM = 768   # text-embedding-004
GEMINI_EMBEDDING_DIM = 768   # text-embedding-004 (same model, different auth)


class HVACEmbedder:
    """Generate embeddings optimized for HVAC technical content.

    Supports multiple providers with automatic fallback:
    - Vertex AI (preferred if configured)
    - OpenAI (fallback)
    """

    def __init__(self):
        settings = get_settings()
        self.provider_preference = settings.embedding_provider
        
        # Initialize OpenAI client
        self._openai_client = None
        self._openai_model = settings.openai_embedding_model
        self._openai_configured = bool(settings.openai_api_key)
        
        # Initialize Vertex AI embedder (lazy)
        self._vertex_embedder = None
        self._vertex_configured: bool | None = None
        
        # Initialize Gemini embedder (lazy) - uses API key
        self._gemini_embedder = None
        self._gemini_configured: bool | None = None
        
        # Determine active provider
        self._active_provider = self._select_provider()
        logger.info(f"EMBEDDER | Initialized | provider={self._active_provider.value}")
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension for active provider."""
        if self._active_provider == EmbeddingProvider.VERTEX:
            return VERTEX_EMBEDDING_DIM
        if self._active_provider == EmbeddingProvider.GEMINI:
            return GEMINI_EMBEDDING_DIM
        return OPENAI_EMBEDDING_DIM
    
    @property
    def openai_client(self) -> AsyncOpenAI:
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            settings = get_settings()
            self._openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._openai_client
    
    @property
    def vertex_embedder(self):
        """Lazy-load Vertex AI embedder."""
        if self._vertex_embedder is None:
            try:
                from services.gcp.embeddings import VertexEmbedder
                embedder = VertexEmbedder()
                if embedder.is_configured:
                    self._vertex_embedder = embedder
                    self._vertex_configured = True
                else:
                    self._vertex_configured = False
            except Exception as e:
                logger.warning(f"EMBEDDER | Vertex AI unavailable: {e}")
                self._vertex_configured = False
        return self._vertex_embedder
    
    @property
    def gemini_embedder(self):
        """Lazy-load Gemini embedder (API key auth)."""
        if self._gemini_embedder is None:
            try:
                from core.gemini import GeminiEmbedder
                embedder = GeminiEmbedder()
                if embedder.is_configured:
                    self._gemini_embedder = embedder
                    self._gemini_configured = True
                else:
                    self._gemini_configured = False
            except Exception as e:
                logger.warning(f"EMBEDDER | Gemini unavailable: {e}")
                self._gemini_configured = False
        return self._gemini_embedder
    
    def _select_provider(self) -> EmbeddingProvider:
        """Select embedding provider based on config and availability."""
        if self.provider_preference == "vertex":
            # Try full Vertex AI first, then Gemini API key, then OpenAI
            if self.vertex_embedder is not None:
                return EmbeddingProvider.VERTEX
            if self.gemini_embedder is not None:
                logger.info("EMBEDDER | Vertex not configured, using Gemini API key")
                return EmbeddingProvider.GEMINI
            logger.warning("EMBEDDER | Vertex/Gemini not configured, falling back to OpenAI")
            return EmbeddingProvider.OPENAI
        
        if self.provider_preference == "gemini":
            if self.gemini_embedder is not None:
                return EmbeddingProvider.GEMINI
            logger.warning("EMBEDDER | Gemini requested but not configured, falling back to OpenAI")
            return EmbeddingProvider.OPENAI
        
        if self.provider_preference == "openai":
            return EmbeddingProvider.OPENAI
        
        # Auto mode: try Gemini first (simpler), then Vertex, then OpenAI
        if self.gemini_embedder is not None:
            return EmbeddingProvider.GEMINI
        if self.vertex_embedder is not None:
            return EmbeddingProvider.VERTEX
        return EmbeddingProvider.OPENAI

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed documents/chunks for storage.

        Args:
            texts: List of document texts to embed

        Returns:
            EmbeddingResult with embeddings
        """
        if not texts:
            return EmbeddingResult(
                embeddings=[],
                model="",
                provider=self._active_provider,
                dimension=self.dimension,
            )
        
        logger.debug(f"EMBEDDER | Embedding {len(texts)} documents | provider={self._active_provider.value}")
        
        # Try Gemini first (API key)
        if self._active_provider == EmbeddingProvider.GEMINI:
            try:
                return await self._embed_with_gemini(texts)
            except Exception as e:
                logger.warning(f"EMBEDDER | Gemini failed, falling back to OpenAI: {e}")
                self._active_provider = EmbeddingProvider.OPENAI
        
        # Try Vertex AI
        if self._active_provider == EmbeddingProvider.VERTEX:
            try:
                return await self._embed_with_vertex(texts)
            except Exception as e:
                logger.warning(f"EMBEDDER | Vertex failed, falling back to OpenAI: {e}")
                self._active_provider = EmbeddingProvider.OPENAI
        
        # OpenAI fallback
        return await self._embed_with_openai(texts)
    
    async def _embed_with_gemini(self, texts: list[str]) -> EmbeddingResult:
        """Embed using Gemini API (API key auth)."""
        embeddings = await self.gemini_embedder.embed_documents(texts)
        
        logger.info(
            f"EMBEDDER | Embedded {len(texts)} docs | "
            f"provider=gemini | dim={GEMINI_EMBEDDING_DIM}"
        )
        
        return EmbeddingResult(
            embeddings=embeddings,
            model="text-embedding-004",
            provider=EmbeddingProvider.GEMINI,
            dimension=GEMINI_EMBEDDING_DIM,
        )
    
    async def _embed_with_vertex(self, texts: list[str]) -> EmbeddingResult:
        """Embed using Vertex AI."""
        embeddings = await self.vertex_embedder.embed_documents(texts)
        
        logger.info(
            f"EMBEDDER | Embedded {len(texts)} docs | "
            f"provider=vertex | dim={VERTEX_EMBEDDING_DIM}"
        )
        
        return EmbeddingResult(
            embeddings=embeddings,
            model="text-embedding-004",
            provider=EmbeddingProvider.VERTEX,
            dimension=VERTEX_EMBEDDING_DIM,
        )
    
    async def _embed_with_openai(self, texts: list[str]) -> EmbeddingResult:
        """Embed using OpenAI with automatic batching for large requests.
        
        OpenAI has a limit of 300,000 tokens per request. We batch to stay safe.
        """
        # Estimate tokens (rough: 1 token ≈ 4 chars for English)
        # Use conservative batch size to stay under 300k token limit
        MAX_TOKENS_PER_BATCH = 250000  # Leave headroom
        CHARS_PER_TOKEN = 4
        
        # Calculate approximate tokens per text
        text_tokens = [(len(t) // CHARS_PER_TOKEN) + 10 for t in texts]  # +10 for overhead
        
        # Create batches that fit within token limit
        batches = []
        current_batch = []
        current_tokens = 0
        
        for i, (text, tokens) in enumerate(zip(texts, text_tokens)):
            if current_tokens + tokens > MAX_TOKENS_PER_BATCH and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(text)
            current_tokens += tokens
        
        if current_batch:
            batches.append(current_batch)
        
        logger.info(f"EMBEDDER | Processing {len(texts)} texts in {len(batches)} batch(es)")
        
        all_embeddings = []
        total_tokens = 0
        
        for batch_idx, batch in enumerate(batches):
            logger.info(f"EMBEDDER |   Batch {batch_idx + 1}/{len(batches)} | {len(batch)} texts")
            
            response = await self.openai_client.embeddings.create(
                input=batch,
                model=self._openai_model,
            )
            
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
            total_tokens += response.usage.total_tokens
        
        embeddings = all_embeddings

        logger.info(
            f"EMBEDDER | Embedded {len(texts)} docs | "
            f"provider=openai | tokens={total_tokens} | dim={len(embeddings[0])}"
        )

        return EmbeddingResult(
            embeddings=embeddings,
            model=self._openai_model,
            provider=EmbeddingProvider.OPENAI,
            dimension=len(embeddings[0]),
            usage={"total_tokens": response.usage.total_tokens},
        )

    async def embed_query(
        self,
        query: str,
        equipment_context: dict[str, Any] | None = None,
    ) -> list[float]:
        """Embed user query for retrieval.

        Args:
            query: User query text
            equipment_context: Optional equipment context to enhance query

        Returns:
            Query embedding vector
        """
        # Enhance query with context
        enhanced_query = query
        if equipment_context:
            context_parts = []
            if equipment_context.get("brand"):
                context_parts.append(f"Brand: {equipment_context['brand']}")
            if equipment_context.get("model"):
                context_parts.append(f"Model: {equipment_context['model']}")
            if context_parts:
                enhanced_query = f"{' | '.join(context_parts)}\n\nQuestion: {query}"

        logger.debug(f"EMBEDDER | Embedding query | length={len(enhanced_query)} | provider={self._active_provider.value}")

        # Use appropriate provider
        if self._active_provider == EmbeddingProvider.GEMINI:
            try:
                embedding = await self.gemini_embedder.embed_query(enhanced_query)
                logger.debug(f"EMBEDDER | Query embedded | provider=gemini | dim={len(embedding)}")
                return embedding
            except Exception as e:
                logger.warning(f"EMBEDDER | Gemini query failed, falling back to OpenAI: {e}")
                self._active_provider = EmbeddingProvider.OPENAI
        
        if self._active_provider == EmbeddingProvider.VERTEX:
            try:
                embedding = await self.vertex_embedder.embed_query(enhanced_query)
                logger.debug(f"EMBEDDER | Query embedded | provider=vertex | dim={len(embedding)}")
                return embedding
            except Exception as e:
                logger.warning(f"EMBEDDER | Vertex query failed, falling back to OpenAI: {e}")
                self._active_provider = EmbeddingProvider.OPENAI
        
        # OpenAI fallback
        response = await self.openai_client.embeddings.create(
            input=[enhanced_query],
            model=self._openai_model,
        )

        embedding = response.data[0].embedding
        logger.debug(f"EMBEDDER | Query embedded | provider=openai | dim={len(embedding)} | tokens={response.usage.total_tokens}")

        return embedding

    def prepare_chunk_for_embedding(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> str:
        """Prepare chunk text for embedding with metadata context.

        This improves retrieval by including searchable context.

        Args:
            content: Chunk content
            metadata: Chunk metadata (brand, model, section, etc.)

        Returns:
            Enhanced text for embedding
        """
        context_parts = []

        # Add equipment context
        if metadata.get("brand"):
            context_parts.append(f"Brand: {metadata['brand']}")
        if metadata.get("model"):
            context_parts.append(f"Model: {metadata['model']}")
        if metadata.get("system_type"):
            context_parts.append(f"System: {metadata['system_type']}")

        # Add section context
        if metadata.get("parent_section"):
            context_parts.append(f"Section: {metadata['parent_section']}")

        # Add chunk type context
        if metadata.get("chunk_type"):
            context_parts.append(f"Type: {metadata['chunk_type']}")

        context = " | ".join(context_parts) if context_parts else ""

        return f"{context}\n\n{content}" if context else content
