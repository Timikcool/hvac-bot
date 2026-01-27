"""Vector store service with multiple provider support.

Supports:
- Qdrant (self-hosted or cloud)
- Vertex AI Vector Search (managed)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from config import get_settings
from core.logging import get_logger

logger = get_logger("rag.vector_store")


class VectorStoreProvider(Enum):
    """Vector store provider options."""
    QDRANT = "qdrant"
    VERTEX = "vertex"


@dataclass
class SearchResult:
    """A single search result."""

    id: str
    content: str
    score: float
    metadata: dict[str, Any]


class VectorStoreProtocol(Protocol):
    """Protocol for vector store implementations."""
    
    async def upsert(
        self,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]: ...
    
    async def search(
        self,
        query_embedding: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        score_threshold: float = 0.5,
    ) -> list[SearchResult]: ...
    
    async def delete_by_document(self, document_id: str) -> int: ...
    
    async def get_stats(self) -> dict[str, Any]: ...


class QdrantVectorStore:
    """Vector store using Qdrant.

    Supports filtering by equipment, chunk type, and hybrid search.
    """

    def __init__(self, embedding_dim: int = 1536):
        """Initialize Qdrant vector store.
        
        Args:
            embedding_dim: Embedding dimension (1536 for OpenAI, 768 for Vertex)
        """
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        
        settings = get_settings()
        self.client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        self.collection_name = settings.qdrant_collection
        self.embedding_dim = embedding_dim
        self._ensure_collection()
        
        logger.info(f"QDRANT | Initialized | collection={self.collection_name} | dim={embedding_dim}")

    def _ensure_collection(self) -> None:
        """Ensure collection exists with proper schema."""
        from qdrant_client.models import Distance, VectorParams
        
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE,
                ),
            )

            # Create payload indexes for filtering
            for field in ["brand", "model", "chunk_type", "system_type", "error_code", "document_type", "document_id", "category"]:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema="keyword",
                )

    async def upsert(
        self,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Store embedded chunks with metadata (batched to prevent timeout)."""
        from qdrant_client.models import PointStruct
        
        if ids is None:
            ids = [str(uuid4()) for _ in embeddings]

        points = []
        for id_, embedding, content, metadata in zip(ids, embeddings, contents, metadatas):
            payload = {
                "content": content,
                "document_id": metadata.get("document_id") or metadata.get("manual_id"),
                "document_type": metadata.get("document_type", "manual"),
                "title": metadata.get("title"),
                "brand": metadata.get("brand"),
                "model": metadata.get("model"),
                "system_type": metadata.get("system_type"),
                "category": metadata.get("category"),
                "chunk_type": metadata.get("chunk_type"),
                "page_numbers": metadata.get("page_numbers", []),
                "parent_section": metadata.get("parent_section"),
                "error_code": metadata.get("error_code"),
                "keywords": metadata.get("keywords", []),
            }

            points.append(
                PointStruct(
                    id=id_,
                    vector=embedding,
                    payload=payload,
                )
            )

        # Batch upserts to prevent timeout on large inserts
        BATCH_SIZE = 100
        total_batches = (len(points) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(points), BATCH_SIZE):
            batch = points[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )
            
            if total_batches > 1:
                logger.info(f"QDRANT | Batch {batch_num}/{total_batches} | {len(batch)} vectors")

        logger.info(f"QDRANT | Upserted {len(points)} vectors total")
        return ids

    async def search(
        self,
        query_embedding: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        score_threshold: float = 0.5,
    ) -> list[SearchResult]:
        """Search for relevant chunks with optional filtering."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        
        filter_conditions = []

        if filters:
            for field in ["brand", "model", "chunk_type", "system_type"]:
                if filters.get(field):
                    filter_conditions.append(
                        FieldCondition(
                            key=field,
                            match=MatchValue(value=filters[field]),
                        )
                    )

        search_filter = Filter(must=filter_conditions) if filter_conditions else None

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
            score_threshold=score_threshold,
        )

        logger.debug(f"QDRANT | Search returned {len(results.points)} results")

        return [
            SearchResult(
                id=str(r.id),
                content=r.payload.get("content", ""),
                score=r.score,
                metadata={
                    k: v for k, v in r.payload.items() if k != "content"
                },
            )
            for r in results.points
        ]

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all chunks from a specific document."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        
        result = self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
        )
        logger.info(f"QDRANT | Deleted vectors for document {document_id}")
        return result.status

    async def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        info = self.client.get_collection(self.collection_name)
        return {
            "provider": "qdrant",
            "collection": self.collection_name,
            "vectors_count": info.points_count,
            "points_count": info.points_count,
            "status": str(info.status),
        }

    async def list_documents(self) -> list[dict[str, Any]]:
        """List all unique documents in the collection with metadata."""
        from collections import defaultdict
        
        # Scroll through all points to collect unique documents
        documents: dict[str, dict] = {}
        chunk_counts: dict[str, int] = defaultdict(int)
        
        # Use scroll to iterate through all points
        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            
            if not results:
                break
            
            for point in results:
                doc_id = point.payload.get("document_id")
                if doc_id and doc_id not in documents:
                    documents[doc_id] = {
                        "document_id": doc_id,
                        "title": point.payload.get("title", "Unknown"),
                        "document_type": point.payload.get("document_type", "manual"),
                        "brand": point.payload.get("brand"),
                        "model": point.payload.get("model"),
                        "system_type": point.payload.get("system_type"),
                        "category": point.payload.get("category"),
                    }
                if doc_id:
                    chunk_counts[doc_id] += 1
            
            if offset is None:
                break
        
        # Add chunk counts to each document
        for doc_id, doc in documents.items():
            doc["chunk_count"] = chunk_counts[doc_id]
        
        logger.info(f"QDRANT | Listed {len(documents)} documents")
        return list(documents.values())


class VertexVectorStoreAdapter:
    """Adapter for Vertex AI Vector Search to match VectorStore interface.
    
    Note: Vertex AI Vector Search requires content to be stored separately
    (e.g., in Firestore or Cloud Storage) since it only stores vectors.
    """
    
    def __init__(self):
        from services.gcp.vector_search import VertexVectorStore
        
        settings = get_settings()
        self._store = VertexVectorStore()
        self._content_cache: dict[str, dict[str, Any]] = {}  # In-memory cache (use Firestore in production)
        
        if not self._store.is_configured:
            raise ValueError("Vertex AI Vector Search not configured")
        
        logger.info("VERTEX | Vector store adapter initialized")
    
    async def upsert(
        self,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Store vectors and cache content."""
        if ids is None:
            ids = [str(uuid4()) for _ in embeddings]
        
        # Store content in cache (use Firestore in production)
        for id_, content, metadata in zip(ids, contents, metadatas):
            self._content_cache[id_] = {
                "content": content,
                **metadata,
            }
        
        # Store vectors in Vertex
        await self._store.upsert(embeddings, contents, metadatas, ids)
        
        return ids
    
    async def search(
        self,
        query_embedding: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        score_threshold: float = 0.5,
    ) -> list[SearchResult]:
        """Search vectors and retrieve content."""
        # Note: Vertex AI Vector Search filtering requires index configuration
        results = await self._store.search(query_embedding, top_k, filters)
        
        search_results = []
        for r in results:
            cached = self._content_cache.get(r.id, {})
            search_results.append(SearchResult(
                id=r.id,
                content=cached.get("content", ""),
                score=r.score,
                metadata={k: v for k, v in cached.items() if k != "content"},
            ))
        
        return search_results
    
    async def delete_by_document(self, document_id: str) -> int:
        """Delete vectors by document ID."""
        # Find IDs to delete from cache
        ids_to_delete = [
            id_ for id_, data in self._content_cache.items()
            if data.get("document_id") == document_id
        ]
        
        if ids_to_delete:
            await self._store.delete(ids_to_delete)
            for id_ in ids_to_delete:
                del self._content_cache[id_]
        
        return len(ids_to_delete)
    
    async def get_stats(self) -> dict[str, Any]:
        """Get store statistics."""
        stats = await self._store.get_stats()
        stats["provider"] = "vertex"
        stats["cached_items"] = len(self._content_cache)
        return stats


class HVACVectorStore:
    """Vector store factory with automatic provider selection.
    
    Supports:
    - Qdrant (default, self-hosted)
    - Vertex AI Vector Search (managed)
    """
    
    def __init__(self, embedding_dim: int | None = None):
        """Initialize vector store with appropriate provider.
        
        Args:
            embedding_dim: Embedding dimension (auto-detected if None)
        """
        settings = get_settings()
        provider = settings.vector_store_provider
        
        # Auto-detect embedding dimension from embedder
        if embedding_dim is None:
            from services.rag.embedder import HVACEmbedder
            embedder = HVACEmbedder()
            embedding_dim = embedder.dimension
        
        self._provider: VectorStoreProvider
        self._store: VectorStoreProtocol
        
        if provider == "vertex":
            try:
                self._store = VertexVectorStoreAdapter()
                self._provider = VectorStoreProvider.VERTEX
                logger.info("VECTOR STORE | Using Vertex AI Vector Search")
            except Exception as e:
                logger.warning(f"VECTOR STORE | Vertex unavailable: {e}, falling back to Qdrant")
                self._store = QdrantVectorStore(embedding_dim)
                self._provider = VectorStoreProvider.QDRANT
        else:
            self._store = QdrantVectorStore(embedding_dim)
            self._provider = VectorStoreProvider.QDRANT
            logger.info("VECTOR STORE | Using Qdrant")
    
    @property
    def provider(self) -> VectorStoreProvider:
        """Get active provider."""
        return self._provider
    
    async def upsert(
        self,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Store embedded chunks with metadata."""
        return await self._store.upsert(embeddings, contents, metadatas, ids)

    async def search(
        self,
        query_embedding: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        score_threshold: float = 0.5,
    ) -> list[SearchResult]:
        """Search for relevant chunks."""
        return await self._store.search(query_embedding, filters, top_k, score_threshold)

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all chunks from a document."""
        return await self._store.delete_by_document(document_id)
    
    async def delete_by_manual(self, manual_id: str) -> int:
        """Alias for delete_by_document (backward compatibility)."""
        return await self.delete_by_document(manual_id)

    async def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        return await self._store.get_stats()

    async def list_documents(self) -> list[dict[str, Any]]:
        """List all unique documents in the collection."""
        if hasattr(self._store, 'list_documents'):
            return await self._store.list_documents()
        return []
