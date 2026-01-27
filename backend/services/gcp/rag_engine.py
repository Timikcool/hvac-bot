"""Vertex AI RAG Engine service.

Provides fully managed RAG (Retrieval-Augmented Generation) using Vertex AI.
Handles corpus management, document ingestion, and grounded generation.
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger("gcp.rag_engine")


@dataclass
class RAGResponse:
    """Response from RAG Engine."""
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    grounding_score: float = 0.0
    model: str = ""


@dataclass
class RAGCorpus:
    """RAG corpus information."""
    name: str
    display_name: str
    description: str
    document_count: int = 0


class VertexRAGEngine:
    """Fully managed RAG using Vertex AI RAG Engine.
    
    Provides:
    - Corpus management (create, update, delete)
    - Document ingestion with automatic chunking and embedding
    - Grounded retrieval with citations
    - Integration with Gemini for generation
    """
    
    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        corpus_name: str | None = None,
    ):
        """Initialize Vertex AI RAG Engine.
        
        Args:
            project_id: GCP project ID
            location: GCP location
            corpus_name: Name of the RAG corpus to use
        """
        from config import get_settings
        settings = get_settings()
        
        self.project_id = project_id or settings.gcp_project_id
        self.location = location or settings.gcp_location
        self.corpus_name = corpus_name or getattr(settings, 'vertex_rag_corpus', '')
        
        self._initialized = False
    
    @property
    def is_configured(self) -> bool:
        """Check if RAG Engine is properly configured."""
        return bool(self.project_id and self.corpus_name)
    
    def _init_vertex(self):
        """Initialize Vertex AI with API key or ADC."""
        if not self._initialized:
            try:
                import os
                import vertexai
                
                # Check for API key first
                api_key = os.environ.get("GOOGLE_CLOUD_API_KEY")
                
                if api_key:
                    # Use API key authentication
                    vertexai.init(
                        project=self.project_id,
                        location=self.location,
                        api_key=api_key,
                    )
                    logger.info(f"VERTEX RAG | Initialized with API key | corpus={self.corpus_name}")
                else:
                    # Fall back to ADC (service account or gcloud auth)
                    vertexai.init(project=self.project_id, location=self.location)
                    logger.info(f"VERTEX RAG | Initialized with ADC | corpus={self.corpus_name}")
                
                self._initialized = True
            except Exception as e:
                logger.error(f"VERTEX RAG | Failed to initialize: {e}")
                raise
    
    async def create_corpus(
        self,
        display_name: str,
        description: str = "",
    ) -> RAGCorpus:
        """Create a new RAG corpus.
        
        Args:
            display_name: Human-readable name
            description: Corpus description
            
        Returns:
            Created corpus info
        """
        self._init_vertex()
        
        logger.info(f"VERTEX RAG | Creating corpus | name={display_name}")
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            corpus = await loop.run_in_executor(
                None,
                lambda: rag.create_corpus(
                    display_name=display_name,
                    description=description,
                )
            )
            
            logger.info(f"VERTEX RAG | Corpus created | name={corpus.name}")
            
            return RAGCorpus(
                name=corpus.name,
                display_name=display_name,
                description=description,
            )
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Failed to create corpus: {e}")
            raise
    
    async def list_corpora(self) -> list[RAGCorpus]:
        """List all RAG corpora.
        
        Returns:
            List of corpus info
        """
        self._init_vertex()
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            corpora = await loop.run_in_executor(
                None,
                lambda: list(rag.list_corpora())
            )
            
            return [
                RAGCorpus(
                    name=c.name,
                    display_name=c.display_name,
                    description=c.description or "",
                )
                for c in corpora
            ]
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Failed to list corpora: {e}")
            raise
    
    async def ingest_document(
        self,
        file_path: str | Path,
        display_name: str | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Ingest a document into the RAG corpus.
        
        Vertex AI RAG Engine handles:
        - Document parsing
        - Chunking
        - Embedding
        - Indexing
        
        Args:
            file_path: Path to document file
            display_name: Optional display name
            description: Document description
            metadata: Additional metadata
            
        Returns:
            Document resource name
        """
        self._init_vertex()
        
        file_path = Path(file_path)
        display_name = display_name or file_path.name
        
        logger.info(f"VERTEX RAG | Ingesting document | file={file_path.name}")
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            
            # Upload file to RAG corpus
            rag_file = await loop.run_in_executor(
                None,
                lambda: rag.upload_file(
                    corpus_name=self.corpus_name,
                    path=str(file_path),
                    display_name=display_name,
                    description=description,
                )
            )
            
            logger.info(f"VERTEX RAG | Document ingested | name={rag_file.name}")
            return rag_file.name
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Failed to ingest document: {e}")
            raise
    
    async def ingest_from_gcs(
        self,
        gcs_uri: str,
        display_name: str | None = None,
    ) -> str:
        """Ingest a document from Google Cloud Storage.
        
        Args:
            gcs_uri: GCS URI (gs://bucket/path/to/file)
            display_name: Optional display name
            
        Returns:
            Document resource name
        """
        self._init_vertex()
        
        display_name = display_name or gcs_uri.split("/")[-1]
        
        logger.info(f"VERTEX RAG | Ingesting from GCS | uri={gcs_uri}")
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            
            # Import from GCS
            response = await loop.run_in_executor(
                None,
                lambda: rag.import_files(
                    corpus_name=self.corpus_name,
                    paths=[gcs_uri],
                )
            )
            
            logger.info(f"VERTEX RAG | Document ingested from GCS")
            return response.imported_rag_files_count
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Failed to ingest from GCS: {e}")
            raise
    
    async def query(
        self,
        question: str,
        top_k: int = 10,
        similarity_threshold: float = 0.5,
    ) -> RAGResponse:
        """Query the RAG corpus and get grounded response.
        
        Args:
            question: User question
            top_k: Number of chunks to retrieve
            similarity_threshold: Minimum similarity score
            
        Returns:
            RAGResponse with answer and sources
        """
        self._init_vertex()
        
        start_time = time.time()
        logger.info(f"VERTEX RAG | Query | q={question[:50]}...")
        
        try:
            from vertexai.preview import rag
            from vertexai.preview.generative_models import GenerativeModel, Tool
            
            loop = asyncio.get_event_loop()
            
            # Create RAG retrieval tool
            rag_retrieval_tool = Tool.from_retrieval(
                retrieval=rag.Retrieval(
                    source=rag.VertexRagStore(
                        rag_corpora=[self.corpus_name],
                        similarity_top_k=top_k,
                        vector_distance_threshold=1 - similarity_threshold,
                    ),
                )
            )
            
            # Create model with RAG tool
            model = GenerativeModel(
                model_name="gemini-1.5-pro",
                tools=[rag_retrieval_tool],
            )
            
            # Generate grounded response
            response = await loop.run_in_executor(
                None,
                lambda: model.generate_content(question)
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Extract answer and sources
            answer = response.text if response.text else ""
            sources = []
            
            # Extract grounding metadata if available
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata'):
                    grounding = candidate.grounding_metadata
                    if hasattr(grounding, 'grounding_chunks'):
                        for chunk in grounding.grounding_chunks:
                            sources.append({
                                "content": chunk.retrieved_context.text if hasattr(chunk, 'retrieved_context') else "",
                                "source": chunk.retrieved_context.uri if hasattr(chunk, 'retrieved_context') else "",
                            })
            
            logger.info(f"VERTEX RAG | Response generated | sources={len(sources)} | time={duration_ms}ms")
            
            return RAGResponse(
                answer=answer,
                sources=sources,
                grounding_score=0.0,  # TODO: Extract from response
                model="gemini-1.5-pro",
            )
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Query failed: {e}")
            raise
    
    async def retrieve_only(
        self,
        query: str,
        top_k: int = 10,
        similarity_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant chunks without generation.
        
        Args:
            query: Search query
            top_k: Number of chunks to retrieve
            similarity_threshold: Minimum similarity score
            
        Returns:
            List of retrieved chunks with metadata
        """
        self._init_vertex()
        
        logger.info(f"VERTEX RAG | Retrieve | q={query[:50]}...")
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            
            response = await loop.run_in_executor(
                None,
                lambda: rag.retrieval_query(
                    rag_corpora=[self.corpus_name],
                    text=query,
                    similarity_top_k=top_k,
                    vector_distance_threshold=1 - similarity_threshold,
                )
            )
            
            chunks = []
            if response.contexts and response.contexts.contexts:
                for ctx in response.contexts.contexts:
                    chunks.append({
                        "content": ctx.text,
                        "source": ctx.source_uri if hasattr(ctx, 'source_uri') else "",
                        "score": ctx.score if hasattr(ctx, 'score') else 0.0,
                    })
            
            logger.info(f"VERTEX RAG | Retrieved {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Retrieve failed: {e}")
            raise
    
    async def delete_document(self, document_name: str) -> None:
        """Delete a document from the corpus.
        
        Args:
            document_name: Document resource name
        """
        self._init_vertex()
        
        logger.info(f"VERTEX RAG | Deleting document | name={document_name}")
        
        try:
            from vertexai.preview import rag
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: rag.delete_file(name=document_name)
            )
            
            logger.info(f"VERTEX RAG | Document deleted")
            
        except Exception as e:
            logger.error(f"VERTEX RAG | Delete failed: {e}")
            raise

