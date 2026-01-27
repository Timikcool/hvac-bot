"""RAG pipeline services.

Supports multiple backends:
- Custom RAG Pipeline: Full control with embedder + retriever + generator
- Vertex AI RAG Engine: Fully managed by Google
"""

from services.rag.embedder import HVACEmbedder, EmbeddingProvider
from services.rag.vector_store import HVACVectorStore, VectorStoreProvider
from services.rag.retriever import HVACRetriever, RetrievalResult
from services.rag.generator import GroundedGenerator, GeneratedResponse
from services.rag.query_processor import QueryProcessor, ProcessedQuery
from services.rag.pipeline import RAGPipeline
from services.rag.unified_rag import UnifiedRAG, RAGProvider

__all__ = [
    # Embeddings
    "HVACEmbedder",
    "EmbeddingProvider",
    # Vector Store
    "HVACVectorStore",
    "VectorStoreProvider",
    # Retrieval
    "HVACRetriever",
    "RetrievalResult",
    # Generation
    "GroundedGenerator",
    "GeneratedResponse",
    # Query Processing
    "QueryProcessor",
    "ProcessedQuery",
    # Pipelines
    "RAGPipeline",
    "UnifiedRAG",
    "RAGProvider",
]
