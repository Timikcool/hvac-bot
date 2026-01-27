"""Vertex AI Vector Search service.

Provides managed vector database using Vertex AI Matching Engine.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from core.logging import get_logger

logger = get_logger("gcp.vector_search")


@dataclass
class VectorSearchResult:
    """Result from vector search."""
    id: str
    score: float
    content: str
    metadata: dict[str, Any]


class VertexVectorStore:
    """Managed vector store using Vertex AI Vector Search.
    
    Provides:
    - Scalable vector storage
    - Fast approximate nearest neighbor search
    - Managed infrastructure
    """
    
    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        index_endpoint_id: str | None = None,
        deployed_index_id: str | None = None,
    ):
        """Initialize Vertex Vector Search.
        
        Args:
            project_id: GCP project ID
            location: GCP location
            index_endpoint_id: Vertex AI index endpoint ID
            deployed_index_id: Deployed index ID within the endpoint
        """
        from config import get_settings
        settings = get_settings()
        
        self.project_id = project_id or settings.gcp_project_id
        self.location = location or settings.gcp_location
        self.index_endpoint_id = index_endpoint_id or getattr(settings, 'vertex_index_endpoint_id', '')
        self.deployed_index_id = deployed_index_id or getattr(settings, 'vertex_deployed_index_id', '')
        
        self._endpoint = None
        self._initialized = False
    
    @property
    def is_configured(self) -> bool:
        """Check if Vector Search is properly configured."""
        return bool(self.project_id and self.index_endpoint_id and self.deployed_index_id)
    
    def _get_endpoint(self):
        """Lazy-load the index endpoint."""
        if self._endpoint is None:
            try:
                import os
                from google.cloud import aiplatform
                
                # Check for API key
                api_key = os.environ.get("GOOGLE_CLOUD_API_KEY")
                
                if api_key:
                    # Use API key authentication
                    aiplatform.init(
                        project=self.project_id,
                        location=self.location,
                        api_key=api_key,
                    )
                    logger.info(f"VERTEX | Vector Search initialized with API key | endpoint={self.index_endpoint_id}")
                else:
                    # Fall back to ADC
                    aiplatform.init(project=self.project_id, location=self.location)
                    logger.info(f"VERTEX | Vector Search initialized with ADC | endpoint={self.index_endpoint_id}")
                
                self._endpoint = aiplatform.MatchingEngineIndexEndpoint(
                    index_endpoint_name=self.index_endpoint_id
                )
                self._initialized = True
            except Exception as e:
                logger.error(f"VERTEX | Failed to initialize Vector Search: {e}")
                raise
        return self._endpoint
    
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Optional metadata filters
            
        Returns:
            List of search results with scores
        """
        start_time = time.time()
        logger.debug(f"VERTEX | Searching | top_k={top_k}")
        
        endpoint = self._get_endpoint()
        
        # Run in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: endpoint.find_neighbors(
                deployed_index_id=self.deployed_index_id,
                queries=[query_embedding],
                num_neighbors=top_k,
            )
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        results = []
        if response and response[0]:
            for neighbor in response[0]:
                results.append(VectorSearchResult(
                    id=neighbor.id,
                    score=neighbor.distance,
                    content="",  # Content needs to be fetched separately
                    metadata={},
                ))
        
        logger.info(f"VERTEX | Search complete | results={len(results)} | time={duration_ms}ms")
        return results
    
    async def upsert(
        self,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Upsert vectors to the index.
        
        Note: Vertex AI Vector Search requires batch updates via GCS.
        For real-time updates, use the streaming update API.
        
        Args:
            embeddings: List of embedding vectors
            contents: List of content strings
            metadatas: List of metadata dicts
            ids: Optional list of IDs (generated if not provided)
            
        Returns:
            List of upserted IDs
        """
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in embeddings]
        
        logger.info(f"VERTEX | Upserting {len(embeddings)} vectors...")
        
        # For Vertex AI Vector Search, we need to:
        # 1. Write vectors to a JSON file in GCS
        # 2. Trigger an index update
        # This is typically done via batch processing
        
        # For now, we'll use the streaming upsert API (if available)
        try:
            from google.cloud import aiplatform
            
            # Prepare datapoints
            datapoints = []
            for i, (id_, embedding) in enumerate(zip(ids, embeddings)):
                datapoint = aiplatform.MatchingEngineIndexEndpoint.Datapoint(
                    datapoint_id=id_,
                    feature_vector=embedding,
                )
                datapoints.append(datapoint)
            
            endpoint = self._get_endpoint()
            
            # Use streaming update
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: endpoint.upsert_datapoints(
                    deployed_index_id=self.deployed_index_id,
                    datapoints=datapoints,
                )
            )
            
            logger.info(f"VERTEX | Upserted {len(ids)} vectors")
            return ids
            
        except Exception as e:
            logger.error(f"VERTEX | Upsert failed: {e}")
            raise
    
    async def delete(self, ids: list[str]) -> None:
        """Delete vectors by ID.
        
        Args:
            ids: List of vector IDs to delete
        """
        logger.info(f"VERTEX | Deleting {len(ids)} vectors...")
        
        try:
            endpoint = self._get_endpoint()
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: endpoint.remove_datapoints(
                    deployed_index_id=self.deployed_index_id,
                    datapoint_ids=ids,
                )
            )
            
            logger.info(f"VERTEX | Deleted {len(ids)} vectors")
            
        except Exception as e:
            logger.error(f"VERTEX | Delete failed: {e}")
            raise
    
    async def get_stats(self) -> dict[str, Any]:
        """Get index statistics.
        
        Returns:
            Dict with index stats
        """
        try:
            endpoint = self._get_endpoint()
            
            return {
                "endpoint_id": self.index_endpoint_id,
                "deployed_index_id": self.deployed_index_id,
                "status": "ready" if self._initialized else "not_initialized",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

