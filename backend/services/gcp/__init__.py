"""Google Cloud Platform services.

Provides integration with Google Cloud:
- Document AI: Document parsing with native table/form extraction
- Vertex AI Embeddings: Text embedding models
- Vertex AI Vector Search: Managed vector database
- Vertex AI RAG Engine: Fully managed RAG pipeline
"""

from services.gcp.document_ai import DocumentAIParser
from services.gcp.embeddings import VertexEmbedder
from services.gcp.vector_search import VertexVectorStore
from services.gcp.rag_engine import VertexRAGEngine

__all__ = [
    "DocumentAIParser",
    "VertexEmbedder",
    "VertexVectorStore",
    "VertexRAGEngine",
]

