"""Vertex AI Embeddings service.

Provides text embeddings using Google's text-embedding models.
"""

import asyncio
from typing import Any

from core.logging import get_logger

logger = get_logger("gcp.embeddings")


class VertexEmbedder:
    """Generate embeddings using Vertex AI.
    
    Uses text-embedding-004 model (768 dimensions).
    """
    
    # Vertex AI embedding dimension
    EMBEDDING_DIM = 768
    
    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        model_name: str = "text-embedding-004",
    ):
        """Initialize Vertex AI embedder.
        
        Args:
            project_id: GCP project ID
            location: GCP location (e.g., us-central1)
            model_name: Embedding model name
        """
        from config import get_settings
        settings = get_settings()
        
        self.project_id = project_id or settings.gcp_project_id
        self.location = location or settings.gcp_location
        self.model_name = model_name
        self._model = None
        self._initialized = False
    
    @property
    def is_configured(self) -> bool:
        """Check if Vertex AI is properly configured."""
        return bool(self.project_id)
    
    def _get_model(self):
        """Lazy-load the embedding model."""
        if self._model is None:
            try:
                import os
                import vertexai
                from vertexai.language_models import TextEmbeddingModel
                
                # Check for API key first
                api_key = os.environ.get("GOOGLE_CLOUD_API_KEY")
                
                if api_key:
                    # Use API key authentication
                    vertexai.init(
                        project=self.project_id,
                        location=self.location,
                        api_key=api_key,
                    )
                    logger.info(f"VERTEX | Embeddings initialized with API key | model={self.model_name}")
                else:
                    # Fall back to ADC
                    vertexai.init(project=self.project_id, location=self.location)
                    logger.info(f"VERTEX | Embeddings initialized with ADC | model={self.model_name}")
                
                self._model = TextEmbeddingModel.from_pretrained(self.model_name)
                self._initialized = True
            except Exception as e:
                logger.error(f"VERTEX | Failed to initialize embeddings: {e}")
                raise
        return self._model
    
    async def embed_documents(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """Embed multiple documents.
        
        Args:
            texts: List of texts to embed
            task_type: Task type for embeddings (RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, etc.)
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        logger.info(f"VERTEX | Embedding {len(texts)} documents...")
        
        model = self._get_model()
        
        # Vertex AI has batch limits, process in chunks
        batch_size = 250  # Vertex AI limit
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            # Run in thread pool since Vertex AI SDK is sync
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: model.get_embeddings(batch, task_type=task_type)
            )
            
            all_embeddings.extend([e.values for e in embeddings])
        
        logger.info(f"VERTEX | Embedded {len(all_embeddings)} documents | dim={self.EMBEDDING_DIM}")
        return all_embeddings
    
    async def embed_query(
        self,
        text: str,
        task_type: str = "RETRIEVAL_QUERY",
    ) -> list[float]:
        """Embed a single query.
        
        Args:
            text: Query text to embed
            task_type: Task type (RETRIEVAL_QUERY for search queries)
            
        Returns:
            Embedding vector
        """
        logger.debug(f"VERTEX | Embedding query | length={len(text)} chars")
        
        model = self._get_model()
        
        # Run in thread pool
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.get_embeddings([text], task_type=task_type)
        )
        
        return embeddings[0].values

