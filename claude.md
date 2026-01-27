# HVAC AI Assistant - Technical Implementation Guide

## 🚀 Production Deployment (Railway)

**Live URLs:**
- Frontend: https://hvac-frontend-production.up.railway.app
- Backend API: https://hvac-api-production.up.railway.app
- API Health: https://hvac-api-production.up.railway.app/api/health

**Infrastructure (all on Railway private network for low latency):**
| Service | Internal Address | Notes |
|---------|------------------|-------|
| PostgreSQL | `postgres.railway.internal:5432` | Conversations, feedback |
| Redis | `redis.railway.internal:6379` | Caching, sessions |
| Qdrant | `qdrant.railway.internal:6333` | 3711 vectors (3 HVAC books) |

**Deployment Commands:**
```bash
# Backend
cd hvac_bot && railway up --service hvac-api

# Frontend  
cd frontend && railway up --service hvac-frontend

# View logs
railway logs -s hvac-api
railway logs -s hvac-frontend
```

See `DEPLOY.md` for full deployment guide and `SETUP.md` for local development.

---

## Project Overview

An AI-powered web application designed for HVAC technicians to diagnose and resolve equipment issues on-site. The system leverages RAG (Retrieval-Augmented Generation) to provide accurate, manual-grounded responses while supporting image recognition for equipment identification and problem diagnosis.

### Core Principles

1. **Accuracy over creativity** - Every response must be traceable to source documentation
2. **Field-first design** - Optimized for mobile use in challenging environments
3. **Safety awareness** - Proactive safety warnings for electrical/refrigerant work
4. **Offline resilience** - Core functionality available without connectivity

---

## System Architecture

```
├── frontend/                  # Next.js PWA
│   ├── components/
│   │   ├── Chat/
│   │   ├── Camera/
│   │   ├── EquipmentSelector/
│   │   └── ManualViewer/
│   ├── hooks/
│   │   ├── useOfflineQueue.ts
│   │   └── useVoiceInput.ts
│   └── pages/
│
├── backend/
│   ├── api/
│   │   ├── chat.py
│   │   ├── image.py
│   │   └── equipment.py
│   ├── services/
│   │   ├── rag/
│   │   ├── vision/
│   │   └── ingestion/
│   └── core/
│       ├── llm.py
│       └── guardrails.py
│
├── ingestion/                 # Document processing pipeline
│   ├── parsers/
│   ├── chunkers/
│   └── embedders/
│
└── infrastructure/
    ├── docker-compose.yml
    └── kubernetes/
```

---

## Feature 1: Document Ingestion Pipeline

### Purpose
Transform HVAC manuals (PDFs, scanned documents, images) into searchable, retrievable chunks stored in a vector database.

### Implementation

#### 1.1 Document Parsing

```python
# backend/services/ingestion/parser.py

from dataclasses import dataclass
from enum import Enum
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
from anthropic import Anthropic

class DocumentType(Enum):
    SERVICE_MANUAL = "service_manual"
    INSTALLATION_GUIDE = "installation_guide"
    PARTS_CATALOG = "parts_catalog"
    WIRING_DIAGRAM = "wiring_diagram"
    TROUBLESHOOTING_GUIDE = "troubleshooting_guide"

@dataclass
class ParsedDocument:
    content: str
    pages: list[dict]
    images: list[dict]
    tables: list[dict]
    metadata: dict

class ManualParser:
    def __init__(self, anthropic_client: Anthropic):
        self.client = anthropic_client

    def parse_pdf(self, file_path: str, metadata: dict) -> ParsedDocument:
        """
        Extract text, images, and tables from PDF manuals.
        Uses PyMuPDF for text extraction and Claude for complex layouts.
        """
        doc = fitz.open(file_path)
        pages = []
        images = []
        tables = []

        for page_num, page in enumerate(doc):
            # Extract text with position info
            text_blocks = page.get_text("dict")["blocks"]
            page_text = page.get_text()

            # Extract images
            for img_index, img in enumerate(page.get_images()):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_data = {
                    "page": page_num + 1,
                    "index": img_index,
                    "bytes": base_image["image"],
                    "ext": base_image["ext"],
                    "description": None  # Will be filled by vision analysis
                }

                # Use Claude vision to describe technical diagrams
                image_data["description"] = self._describe_image(
                    base_image["image"],
                    context=f"Page {page_num + 1} of {metadata.get('title', 'HVAC manual')}"
                )
                images.append(image_data)

            # Detect and extract tables
            page_tables = self._extract_tables(page)
            tables.extend(page_tables)

            pages.append({
                "page_number": page_num + 1,
                "text": page_text,
                "blocks": text_blocks
            })

        return ParsedDocument(
            content="\n\n".join(p["text"] for p in pages),
            pages=pages,
            images=images,
            tables=tables,
            metadata=metadata
        )

    def _describe_image(self, image_bytes: bytes, context: str) -> str:
        """Use Claude vision to generate searchable descriptions of diagrams."""
        import base64

        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": f"""Describe this HVAC technical diagram/image for search indexing.
                        Context: {context}

                        Include:
                        - Type of diagram (wiring, refrigerant flow, exploded view, etc.)
                        - Components shown
                        - Any labels, part numbers, or specifications visible
                        - What this diagram is used for

                        Be factual and technical. This will be used for retrieval."""
                    }
                ]
            }]
        )

        return response.content[0].text

    def _extract_tables(self, page) -> list[dict]:
        """Extract specification tables, error code tables, etc."""
        # Use tabula-py or camelot for table extraction
        # Falls back to Claude for complex/merged cell tables
        tables = []
        # Implementation details...
        return tables


class OCRProcessor:
    """Handle scanned documents and images of manuals."""

    def __init__(self):
        self.tesseract_config = '--oem 3 --psm 6'

    def process_scanned_pdf(self, file_path: str) -> str:
        """OCR scanned PDF pages."""
        doc = fitz.open(file_path)
        full_text = []

        for page in doc:
            # Render page to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better OCR
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # OCR
            text = pytesseract.image_to_string(img, config=self.tesseract_config)
            full_text.append(text)

        return "\n\n".join(full_text)

    def extract_model_plate(self, image: Image) -> dict:
        """
        Extract model/serial number from equipment nameplate photo.
        Returns structured equipment identification data.
        """
        # Pre-process image for better OCR
        # - Deskew
        # - Contrast enhancement
        # - Noise reduction

        text = pytesseract.image_to_string(image, config=self.tesseract_config)

        # Pattern matching for common HVAC manufacturers
        patterns = {
            "carrier": r"(?:Model|Mod)[:\s]*([A-Z0-9-]+)",
            "trane": r"(?:M/N|Model)[:\s]*([A-Z0-9-]+)",
            "lennox": r"(?:Model)[:\s]*([A-Z0-9-]+)",
            # Add more manufacturers...
        }

        # Extract and return structured data
        return self._parse_nameplate_text(text, patterns)
```

#### 1.2 Intelligent Chunking

```python
# backend/services/ingestion/chunker.py

from dataclasses import dataclass
from enum import Enum
import re

class ChunkType(Enum):
    TROUBLESHOOTING_STEP = "troubleshooting_step"
    SPECIFICATION = "specification"
    PROCEDURE = "procedure"
    SAFETY_WARNING = "safety_warning"
    ERROR_CODE = "error_code"
    WIRING_INFO = "wiring_info"
    GENERAL = "general"

@dataclass
class Chunk:
    content: str
    chunk_type: ChunkType
    metadata: dict
    page_numbers: list[int]
    parent_section: str
    has_image_reference: bool

class HVACChunker:
    """
    HVAC-aware document chunker that preserves semantic boundaries.
    Unlike generic chunkers, this understands HVAC document structure.
    """

    def __init__(self, max_chunk_size: int = 1500, overlap: int = 200):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

        # Patterns that should never be split
        self.atomic_patterns = [
            r"(?:CAUTION|WARNING|DANGER):.*?(?=\n\n|\Z)",  # Safety warnings
            r"(?:Step \d+[.:]).*?(?=Step \d+|$)",  # Procedure steps
            r"(?:Error|Fault|Code)\s+[A-Z0-9]+:.*?(?=(?:Error|Fault|Code)\s+[A-Z0-9]+|$)",  # Error codes
        ]

    def chunk_document(self, parsed_doc: ParsedDocument) -> list[Chunk]:
        """
        Create semantically meaningful chunks from parsed document.
        Preserves troubleshooting sequences, specifications, and procedures.
        """
        chunks = []

        # First pass: identify document sections
        sections = self._identify_sections(parsed_doc.content)

        for section in sections:
            section_type = self._classify_section(section)

            if section_type == ChunkType.TROUBLESHOOTING_STEP:
                # Keep troubleshooting flows together
                chunks.extend(self._chunk_troubleshooting(section, parsed_doc.metadata))

            elif section_type == ChunkType.ERROR_CODE:
                # Each error code is its own chunk
                chunks.extend(self._chunk_error_codes(section, parsed_doc.metadata))

            elif section_type == ChunkType.SPECIFICATION:
                # Keep spec tables together
                chunks.extend(self._chunk_specifications(section, parsed_doc.metadata))

            elif section_type == ChunkType.SAFETY_WARNING:
                # Safety warnings are atomic - never split
                chunks.append(Chunk(
                    content=section["content"],
                    chunk_type=ChunkType.SAFETY_WARNING,
                    metadata={**parsed_doc.metadata, "priority": "high"},
                    page_numbers=section["pages"],
                    parent_section=section["title"],
                    has_image_reference=False
                ))

            else:
                # Generic chunking with overlap
                chunks.extend(self._chunk_generic(section, parsed_doc.metadata))

        return chunks

    def _chunk_troubleshooting(self, section: dict, base_metadata: dict) -> list[Chunk]:
        """
        Special handling for troubleshooting sections.
        Keeps symptom -> cause -> solution sequences together.
        """
        chunks = []
        content = section["content"]

        # Pattern: "Problem: X ... Cause: Y ... Solution: Z"
        troubleshooting_pattern = r"(?:Problem|Symptom|Issue)[:\s]+(.*?)(?:Cause|Reason)[:\s]+(.*?)(?:Solution|Fix|Action|Remedy)[:\s]+(.*?)(?=(?:Problem|Symptom|Issue)[:\s]+|\Z)"

        matches = re.finditer(troubleshooting_pattern, content, re.DOTALL | re.IGNORECASE)

        for match in matches:
            problem, cause, solution = match.groups()

            chunk_content = f"""PROBLEM: {problem.strip()}

CAUSE: {cause.strip()}

SOLUTION: {solution.strip()}"""

            chunks.append(Chunk(
                content=chunk_content,
                chunk_type=ChunkType.TROUBLESHOOTING_STEP,
                metadata={
                    **base_metadata,
                    "symptom_keywords": self._extract_keywords(problem),
                    "component_keywords": self._extract_component_names(cause + solution)
                },
                page_numbers=section["pages"],
                parent_section=section["title"],
                has_image_reference="fig" in content.lower() or "diagram" in content.lower()
            ))

        return chunks

    def _chunk_error_codes(self, section: dict, base_metadata: dict) -> list[Chunk]:
        """Extract individual error codes as separate chunks for precise retrieval."""
        chunks = []
        content = section["content"]

        # Common error code patterns
        error_pattern = r"(?:Error|Fault|Code|E|F)\s*[-:]?\s*([A-Z]?\d{1,3})[:\s]+([^\n]+(?:\n(?![A-Z]?\d{1,3}[:\s]).*)*)"

        for match in re.finditer(error_pattern, content):
            code, description = match.groups()

            chunks.append(Chunk(
                content=f"Error Code {code}: {description.strip()}",
                chunk_type=ChunkType.ERROR_CODE,
                metadata={
                    **base_metadata,
                    "error_code": code,
                    "searchable_code": f"E{code} F{code} error{code} fault{code}"
                },
                page_numbers=section["pages"],
                parent_section="Error Codes",
                has_image_reference=False
            ))

        return chunks

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract HVAC-relevant keywords for enhanced retrieval."""
        hvac_terms = [
            "compressor", "condenser", "evaporator", "refrigerant", "thermostat",
            "blower", "fan", "motor", "capacitor", "contactor", "relay",
            "pressure", "temperature", "superheat", "subcooling", "charge",
            "leak", "frozen", "icing", "short cycling", "not cooling", "not heating",
            "noise", "vibration", "tripping", "breaker", "fuse"
        ]

        text_lower = text.lower()
        return [term for term in hvac_terms if term in text_lower]

    def _extract_component_names(self, text: str) -> list[str]:
        """Extract component names for filtering."""
        components = []
        # Pattern matching for part numbers, component names
        # Implementation...
        return components
```

#### 1.3 Embedding and Storage

```python
# backend/services/ingestion/embedder.py

from anthropic import Anthropic
import voyageai  # or use OpenAI embeddings
from dataclasses import dataclass
import numpy as np

@dataclass
class EmbeddedChunk:
    chunk: Chunk
    embedding: list[float]
    sparse_vector: dict  # For hybrid search

class HVACEmbedder:
    """
    Generate embeddings optimized for HVAC technical content.
    Uses hybrid approach: dense embeddings + sparse vectors for technical terms.
    """

    def __init__(self):
        # Voyage AI has good technical document embeddings
        # Alternative: OpenAI text-embedding-3-large
        self.voyage_client = voyageai.Client()
        self.model = "voyage-large-2"  # or voyage-code-2 for technical docs

    def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """Generate embeddings for chunks with HVAC-specific enhancements."""
        embedded = []

        # Batch embedding for efficiency
        texts = [self._prepare_for_embedding(chunk) for chunk in chunks]

        embeddings = self.voyage_client.embed(
            texts=texts,
            model=self.model,
            input_type="document"
        ).embeddings

        for chunk, embedding in zip(chunks, embeddings):
            embedded.append(EmbeddedChunk(
                chunk=chunk,
                embedding=embedding,
                sparse_vector=self._create_sparse_vector(chunk)
            ))

        return embedded

    def _prepare_for_embedding(self, chunk: Chunk) -> str:
        """
        Prepare chunk text for embedding with metadata context.
        This improves retrieval by including searchable context.
        """
        context_parts = []

        # Add equipment context
        if chunk.metadata.get("brand"):
            context_parts.append(f"Brand: {chunk.metadata['brand']}")
        if chunk.metadata.get("model"):
            context_parts.append(f"Model: {chunk.metadata['model']}")
        if chunk.metadata.get("system_type"):
            context_parts.append(f"System: {chunk.metadata['system_type']}")

        # Add section context
        if chunk.parent_section:
            context_parts.append(f"Section: {chunk.parent_section}")

        # Add chunk type context
        context_parts.append(f"Type: {chunk.chunk_type.value}")

        context = " | ".join(context_parts)

        return f"{context}\n\n{chunk.content}"

    def _create_sparse_vector(self, chunk: Chunk) -> dict:
        """
        Create sparse vector for hybrid search.
        Boosts exact matches on technical terms, model numbers, error codes.
        """
        sparse = {}

        # Boost error codes
        if chunk.chunk_type == ChunkType.ERROR_CODE:
            code = chunk.metadata.get("error_code", "")
            sparse[f"error_{code}"] = 2.0
            sparse[f"E{code}"] = 2.0
            sparse[f"F{code}"] = 2.0

        # Boost model numbers
        if chunk.metadata.get("model"):
            sparse[chunk.metadata["model"]] = 1.5

        # Boost component keywords
        for keyword in chunk.metadata.get("component_keywords", []):
            sparse[keyword] = 1.2

        return sparse

    def embed_query(self, query: str, equipment_context: dict = None) -> list[float]:
        """
        Embed user query with optional equipment context.
        Uses 'query' input type for asymmetric retrieval.
        """
        # Enhance query with context
        enhanced_query = query
        if equipment_context:
            context = f"Equipment: {equipment_context.get('brand', '')} {equipment_context.get('model', '')}"
            enhanced_query = f"{context}\n\nQuestion: {query}"

        embedding = self.voyage_client.embed(
            texts=[enhanced_query],
            model=self.model,
            input_type="query"
        ).embeddings[0]

        return embedding
```

#### 1.4 Vector Database Schema

```python
# backend/services/ingestion/vector_store.py

from pinecone import Pinecone
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue
)
import uuid

class HVACVectorStore:
    """
    Vector store optimized for HVAC manual retrieval.
    Supports filtering by equipment, chunk type, and hybrid search.
    """

    def __init__(self, provider: str = "qdrant"):
        if provider == "qdrant":
            self.client = QdrantClient(host="localhost", port=6333)
            self._init_qdrant()
        elif provider == "pinecone":
            self.client = Pinecone()
            self._init_pinecone()

    def _init_qdrant(self):
        """Initialize Qdrant collection with proper schema."""

        # Check if collection exists
        collections = self.client.get_collections().collections
        if "hvac_manuals" not in [c.name for c in collections]:
            self.client.create_collection(
                collection_name="hvac_manuals",
                vectors_config=VectorParams(
                    size=1024,  # Voyage large embedding size
                    distance=Distance.COSINE
                )
            )

            # Create payload indexes for filtering
            self.client.create_payload_index(
                collection_name="hvac_manuals",
                field_name="brand",
                field_schema="keyword"
            )
            self.client.create_payload_index(
                collection_name="hvac_manuals",
                field_name="model",
                field_schema="keyword"
            )
            self.client.create_payload_index(
                collection_name="hvac_manuals",
                field_name="chunk_type",
                field_schema="keyword"
            )
            self.client.create_payload_index(
                collection_name="hvac_manuals",
                field_name="system_type",
                field_schema="keyword"
            )

    def upsert_chunks(self, embedded_chunks: list[EmbeddedChunk]):
        """Store embedded chunks with full metadata."""
        points = []

        for ec in embedded_chunks:
            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=ec.embedding,
                payload={
                    "content": ec.chunk.content,
                    "chunk_type": ec.chunk.chunk_type.value,
                    "brand": ec.chunk.metadata.get("brand"),
                    "model": ec.chunk.metadata.get("model"),
                    "system_type": ec.chunk.metadata.get("system_type"),
                    "manual_id": ec.chunk.metadata.get("manual_id"),
                    "manual_title": ec.chunk.metadata.get("title"),
                    "page_numbers": ec.chunk.page_numbers,
                    "parent_section": ec.chunk.parent_section,
                    "has_image": ec.chunk.has_image_reference,
                    "error_code": ec.chunk.metadata.get("error_code"),
                    "keywords": ec.chunk.metadata.get("symptom_keywords", []) +
                               ec.chunk.metadata.get("component_keywords", [])
                }
            )
            points.append(point)

        # Batch upsert
        self.client.upsert(
            collection_name="hvac_manuals",
            points=points,
            batch_size=100
        )

    def search(
        self,
        query_embedding: list[float],
        filters: dict = None,
        top_k: int = 10
    ) -> list[dict]:
        """
        Search for relevant chunks with optional filtering.

        Filters can include:
        - brand: str
        - model: str
        - system_type: str (split, package, mini-split, etc.)
        - chunk_type: str (troubleshooting_step, error_code, etc.)
        """
        filter_conditions = []

        if filters:
            if filters.get("brand"):
                filter_conditions.append(
                    FieldCondition(
                        key="brand",
                        match=MatchValue(value=filters["brand"])
                    )
                )
            if filters.get("model"):
                filter_conditions.append(
                    FieldCondition(
                        key="model",
                        match=MatchValue(value=filters["model"])
                    )
                )
            if filters.get("chunk_type"):
                filter_conditions.append(
                    FieldCondition(
                        key="chunk_type",
                        match=MatchValue(value=filters["chunk_type"])
                    )
                )

        search_filter = Filter(must=filter_conditions) if filter_conditions else None

        results = self.client.search(
            collection_name="hvac_manuals",
            query_vector=query_embedding,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
            score_threshold=0.5  # Minimum relevance threshold
        )

        return [
            {
                "content": r.payload["content"],
                "score": r.score,
                "metadata": r.payload
            }
            for r in results
        ]
```

---

## Feature 2: RAG Pipeline with Grounded Responses

### Purpose
Generate accurate, citation-backed responses that strictly adhere to manual content without hallucination.

### Implementation

#### 2.1 Query Processing

```python
# backend/services/rag/query_processor.py

from dataclasses import dataclass
from anthropic import Anthropic

@dataclass
class ProcessedQuery:
    original: str
    enhanced: str
    intent: str
    equipment_hints: dict
    urgency: str  # "routine", "urgent", "safety"

class QueryProcessor:
    """
    Process and enhance user queries for optimal retrieval.
    Extracts intent, equipment references, and urgency level.
    """

    def __init__(self, anthropic_client: Anthropic):
        self.client = anthropic_client

    def process(self, query: str, conversation_history: list = None) -> ProcessedQuery:
        """
        Analyze and enhance the user query.
        Uses Claude for query understanding and expansion.
        """

        # Use Claude to understand the query
        analysis_prompt = f"""Analyze this HVAC technician query:

Query: "{query}"

Previous conversation context: {conversation_history[-3:] if conversation_history else "None"}

Extract:
1. PRIMARY_INTENT: What is the technician trying to do? (diagnose, repair, install, maintain, find_spec, understand_error)
2. EQUIPMENT_TYPE: What type of equipment? (air_conditioner, heat_pump, furnace, boiler, mini_split, chiller, rooftop_unit, unknown)
3. BRAND_HINTS: Any brand names mentioned or implied?
4. MODEL_HINTS: Any model numbers or series mentioned?
5. SYMPTOMS: Key symptoms or issues described
6. COMPONENT_FOCUS: Specific components mentioned
7. URGENCY: Is this routine, urgent (customer waiting), or safety-related?
8. SEARCH_TERMS: Generate 3-5 alternative search phrases that would find relevant manual sections

Respond in JSON format."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": analysis_prompt}]
        )

        analysis = self._parse_json_response(response.content[0].text)

        # Build enhanced query for better retrieval
        enhanced_parts = [query]
        if analysis.get("symptoms"):
            enhanced_parts.extend(analysis["symptoms"])
        if analysis.get("search_terms"):
            enhanced_parts.extend(analysis["search_terms"][:2])

        return ProcessedQuery(
            original=query,
            enhanced=" ".join(enhanced_parts),
            intent=analysis.get("PRIMARY_INTENT", "diagnose"),
            equipment_hints={
                "type": analysis.get("EQUIPMENT_TYPE"),
                "brand": analysis.get("BRAND_HINTS"),
                "model": analysis.get("MODEL_HINTS"),
                "component": analysis.get("COMPONENT_FOCUS")
            },
            urgency=analysis.get("URGENCY", "routine")
        )

    def _parse_json_response(self, text: str) -> dict:
        """Safely parse JSON from Claude response."""
        import json
        import re

        # Extract JSON from response
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}
```

#### 2.2 Retrieval with Re-ranking

```python
# backend/services/rag/retriever.py

from dataclasses import dataclass

@dataclass
class RetrievalResult:
    chunks: list[dict]
    total_found: int
    filters_applied: dict
    retrieval_strategy: str

class HVACRetriever:
    """
    Multi-stage retrieval optimized for HVAC technical queries.
    Uses query enhancement, filtering, and re-ranking.
    """

    def __init__(self, vector_store: HVACVectorStore, embedder: HVACEmbedder):
        self.vector_store = vector_store
        self.embedder = embedder
        self.reranker = CrossEncoderReranker()  # For re-ranking results

    def retrieve(
        self,
        processed_query: ProcessedQuery,
        equipment_context: dict,
        top_k: int = 10
    ) -> RetrievalResult:
        """
        Multi-stage retrieval:
        1. Dense retrieval with filters
        2. Keyword boosting for technical terms
        3. Cross-encoder re-ranking
        4. Diversity sampling
        """

        # Stage 1: Build filters from equipment context
        filters = self._build_filters(processed_query, equipment_context)

        # Stage 2: Dense retrieval (retrieve more than needed for re-ranking)
        query_embedding = self.embedder.embed_query(
            processed_query.enhanced,
            equipment_context
        )

        initial_results = self.vector_store.search(
            query_embedding=query_embedding,
            filters=filters,
            top_k=top_k * 3  # Over-retrieve for re-ranking
        )

        # Stage 3: If equipment-specific search yields few results, broaden search
        if len(initial_results) < 5 and filters.get("model"):
            # Remove model filter, keep brand
            broader_filters = {k: v for k, v in filters.items() if k != "model"}
            broader_results = self.vector_store.search(
                query_embedding=query_embedding,
                filters=broader_filters,
                top_k=top_k * 2
            )
            initial_results.extend(broader_results)

        # Stage 4: Re-rank with cross-encoder
        if len(initial_results) > top_k:
            reranked = self.reranker.rerank(
                query=processed_query.original,
                documents=[r["content"] for r in initial_results],
                top_k=top_k
            )
            final_results = [initial_results[i] for i in reranked]
        else:
            final_results = initial_results

        # Stage 5: Ensure diversity (don't return 5 chunks from same section)
        final_results = self._ensure_diversity(final_results, max_per_section=2)

        return RetrievalResult(
            chunks=final_results,
            total_found=len(initial_results),
            filters_applied=filters,
            retrieval_strategy="dense_filtered_reranked"
        )

    def _build_filters(self, query: ProcessedQuery, equipment: dict) -> dict:
        """Build vector store filters from query and equipment context."""
        filters = {}

        # Equipment-specific filters
        if equipment.get("brand"):
            filters["brand"] = equipment["brand"]
        if equipment.get("model"):
            filters["model"] = equipment["model"]

        # Intent-based chunk type filtering
        if query.intent == "understand_error":
            filters["chunk_type"] = "error_code"
        elif query.intent == "find_spec":
            filters["chunk_type"] = "specification"

        return filters

    def _ensure_diversity(self, results: list, max_per_section: int = 2) -> list:
        """Prevent over-representation from single manual section."""
        section_counts = {}
        diverse_results = []

        for result in results:
            section = result["metadata"].get("parent_section", "unknown")
            if section_counts.get(section, 0) < max_per_section:
                diverse_results.append(result)
                section_counts[section] = section_counts.get(section, 0) + 1

        return diverse_results


class CrossEncoderReranker:
    """Re-rank results using cross-encoder for better relevance."""

    def __init__(self):
        from sentence_transformers import CrossEncoder
        # Use a cross-encoder trained on technical/scientific data
        self.model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-12-v2')

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[int]:
        """Return indices of top_k most relevant documents."""
        pairs = [[query, doc] for doc in documents]
        scores = self.model.predict(pairs)

        # Get indices sorted by score
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked_indices[:top_k]
```

#### 2.3 Grounded Response Generation

```python
# backend/services/rag/generator.py

from dataclasses import dataclass
from anthropic import Anthropic
from enum import Enum

class ConfidenceLevel(Enum):
    HIGH = "high"      # Direct answer found in manuals
    MEDIUM = "medium"  # Partial information, some inference needed
    LOW = "low"        # Limited relevant information
    NONE = "none"      # No relevant information found

@dataclass
class GeneratedResponse:
    answer: str
    confidence: ConfidenceLevel
    citations: list[dict]
    safety_warnings: list[str]
    suggested_followups: list[str]
    requires_escalation: bool

class GroundedGenerator:
    """
    Generate responses strictly grounded in retrieved manual content.
    Implements multiple guardrails against hallucination.
    """

    def __init__(self, anthropic_client: Anthropic):
        self.client = anthropic_client

    def generate(
        self,
        query: str,
        retrieved_chunks: list[dict],
        equipment_context: dict,
        conversation_history: list = None
    ) -> GeneratedResponse:
        """
        Generate a grounded response with citations.
        Uses structured prompting to prevent hallucination.
        """

        # Format retrieved chunks with source identifiers
        formatted_sources = self._format_sources(retrieved_chunks)

        # Check if we have sufficient information
        if not retrieved_chunks or all(c["score"] < 0.6 for c in retrieved_chunks):
            return self._generate_insufficient_info_response(query, equipment_context)

        system_prompt = """You are an HVAC technical assistant helping field technicians.
Your responses must be STRICTLY based on the provided manual excerpts.

CRITICAL RULES:
1. ONLY answer based on information in the provided sources
2. If the sources don't contain the answer, say "I don't have this information in the available manuals"
3. NEVER make up specifications, procedures, or troubleshooting steps
4. ALWAYS cite your sources using [Source X] notation
5. If sources are ambiguous or contradictory, note this explicitly
6. Prioritize safety - always include relevant warnings from the manuals
7. Be concise - technicians need quick answers in the field

RESPONSE FORMAT:
- Start with direct answer to the question
- Include step-by-step instructions if applicable
- Cite sources for each claim: [Source 1], [Source 2]
- Add safety warnings if relevant (from manuals)
- Keep it practical and actionable"""

        user_prompt = f"""EQUIPMENT CONTEXT:
- Brand: {equipment_context.get('brand', 'Unknown')}
- Model: {equipment_context.get('model', 'Unknown')}
- System Type: {equipment_context.get('system_type', 'Unknown')}

AVAILABLE SOURCES:
{formatted_sources}

TECHNICIAN'S QUESTION:
{query}

Remember: Only answer based on the sources above. Cite each source used."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            temperature=0.1,  # Low temperature for factual responses
            system=system_prompt,
            messages=[
                *self._format_history(conversation_history),
                {"role": "user", "content": user_prompt}
            ]
        )

        answer = response.content[0].text

        # Post-process response
        citations = self._extract_citations(answer, retrieved_chunks)
        safety_warnings = self._extract_safety_warnings(answer, retrieved_chunks)
        confidence = self._assess_confidence(answer, retrieved_chunks)

        return GeneratedResponse(
            answer=answer,
            confidence=confidence,
            citations=citations,
            safety_warnings=safety_warnings,
            suggested_followups=self._generate_followups(query, answer),
            requires_escalation=confidence == ConfidenceLevel.LOW
        )

    def _format_sources(self, chunks: list[dict]) -> str:
        """Format retrieved chunks as numbered sources."""
        formatted = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            source_header = f"[Source {i}] {meta.get('manual_title', 'Manual')}"
            if meta.get("page_numbers"):
                source_header += f", Page(s) {meta['page_numbers']}"
            if meta.get("parent_section"):
                source_header += f", Section: {meta['parent_section']}"

            formatted.append(f"{source_header}\n{chunk['content']}\n")

        return "\n---\n".join(formatted)

    def _assess_confidence(self, answer: str, chunks: list[dict]) -> ConfidenceLevel:
        """Assess confidence based on retrieval scores and answer content."""

        # Check for uncertainty phrases
        uncertainty_phrases = [
            "don't have this information",
            "not found in",
            "no specific information",
            "cannot confirm",
            "may need to consult"
        ]

        if any(phrase in answer.lower() for phrase in uncertainty_phrases):
            return ConfidenceLevel.LOW

        # Check retrieval scores
        avg_score = sum(c["score"] for c in chunks) / len(chunks) if chunks else 0

        if avg_score > 0.8:
            return ConfidenceLevel.HIGH
        elif avg_score > 0.65:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    def _extract_citations(self, answer: str, chunks: list[dict]) -> list[dict]:
        """Extract and validate citations from the answer."""
        import re

        citations = []
        citation_pattern = r'\[Source (\d+)\]'

        for match in re.finditer(citation_pattern, answer):
            source_num = int(match.group(1)) - 1
            if 0 <= source_num < len(chunks):
                chunk = chunks[source_num]
                citations.append({
                    "source_number": source_num + 1,
                    "manual": chunk["metadata"].get("manual_title"),
                    "page": chunk["metadata"].get("page_numbers"),
                    "section": chunk["metadata"].get("parent_section"),
                    "manual_id": chunk["metadata"].get("manual_id")  # For linking to PDF viewer
                })

        return citations

    def _extract_safety_warnings(self, answer: str, chunks: list[dict]) -> list[str]:
        """Extract safety-relevant information from sources."""
        warnings = []

        for chunk in chunks:
            content = chunk["content"].lower()
            if chunk["metadata"].get("chunk_type") == "safety_warning":
                warnings.append(chunk["content"])
            elif any(term in content for term in ["warning", "caution", "danger", "hazard"]):
                # Extract warning sentences
                import re
                warning_pattern = r'(?:WARNING|CAUTION|DANGER)[:\s]+([^.!]+[.!])'
                matches = re.findall(warning_pattern, chunk["content"], re.IGNORECASE)
                warnings.extend(matches)

        return list(set(warnings))  # Deduplicate

    def _generate_insufficient_info_response(self, query: str, equipment: dict) -> GeneratedResponse:
        """Generate response when no relevant information is found."""
        return GeneratedResponse(
            answer=f"""I don't have specific information about this in the available manuals for {equipment.get('brand', 'this equipment')} {equipment.get('model', '')}.

This could mean:
1. The manual for this specific model hasn't been uploaded yet
2. This issue isn't covered in the service manual
3. You may need the installation guide or parts manual instead

Suggested actions:
- Check if you have the correct model selected
- Try rephrasing your question with different terms
- Consult the physical manual or contact technical support""",
            confidence=ConfidenceLevel.NONE,
            citations=[],
            safety_warnings=[],
            suggested_followups=[
                "Do you want me to search across all brands?",
                "Can you provide more details about the symptom?",
                "Would you like to try a different model number?"
            ],
            requires_escalation=True
        )

    def _format_history(self, history: list) -> list:
        """Format conversation history for context."""
        if not history:
            return []

        formatted = []
        for msg in history[-6:]:  # Keep last 6 messages for context
            formatted.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        return formatted

    def _generate_followups(self, query: str, answer: str) -> list[str]:
        """Generate relevant follow-up questions."""
        # Could use Claude to generate these dynamically
        # For now, use rule-based suggestions
        followups = []

        if "compressor" in query.lower() or "compressor" in answer.lower():
            followups.append("What are the compressor amp draw specifications?")
        if "refrigerant" in query.lower() or "refrigerant" in answer.lower():
            followups.append("What is the factory refrigerant charge for this unit?")
        if "error" in query.lower() or "code" in query.lower():
            followups.append("How do I clear/reset this error code?")

        return followups[:3]
```

---

## Feature 3: Image Recognition Module

### Purpose
Enable technicians to photograph equipment nameplates for automatic identification and capture images of problems for visual diagnosis.

### Implementation

#### 3.1 Equipment Identification via Nameplate

```python
# backend/services/vision/nameplate_reader.py

from dataclasses import dataclass
from anthropic import Anthropic
from PIL import Image
import base64
import io
import re

@dataclass
class EquipmentIdentification:
    brand: str
    model: str
    serial: str
    manufacture_date: str
    specs: dict
    confidence: float
    raw_text: str

class NameplateReader:
    """
    Extract equipment information from nameplate/data plate photos.
    Uses Claude vision with HVAC-specific prompting.
    """

    def __init__(self, anthropic_client: Anthropic):
        self.client = anthropic_client

        # Known manufacturer patterns for validation
        self.manufacturer_patterns = {
            "carrier": {
                "model_pattern": r"(?:24|25|38|40|48|50)[A-Z]{2,3}\d{3,6}",
                "serial_pattern": r"\d{10}"
            },
            "trane": {
                "model_pattern": r"(?:4TT|4WC|XR|XL|XV)\w+",
                "serial_pattern": r"\d{9,10}"
            },
            "lennox": {
                "model_pattern": r"(?:XC|EL|ML|SL)\d{2}[A-Z]-\d{3}",
                "serial_pattern": r"\d{10}[A-Z]"
            },
            "rheem": {
                "model_pattern": r"R\d{2}[A-Z]{2}\d{4}",
                "serial_pattern": r"[A-Z]\d{10}"
            },
            "goodman": {
                "model_pattern": r"G[A-Z]{2,3}\d{4,6}",
                "serial_pattern": r"\d{10}"
            }
            # Add more manufacturers...
        }

    def read_nameplate(self, image: bytes) -> EquipmentIdentification:
        """
        Read equipment nameplate using Claude vision.
        Returns structured equipment identification data.
        """

        image_b64 = base64.standard_b64encode(image).decode("utf-8")

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": """Analyze this HVAC equipment nameplate/data plate and extract:

1. MANUFACTURER/BRAND: (e.g., Carrier, Trane, Lennox, Rheem, Goodman, etc.)
2. MODEL NUMBER: The complete model/part number
3. SERIAL NUMBER: The serial number
4. MANUFACTURE DATE: Date or date code if visible
5. SPECIFICATIONS:
   - Voltage/Phase (e.g., 208-230V/1Ph/60Hz)
   - Amperage ratings (RLA, LRA, FLA)
   - BTU/Tonnage if shown
   - Refrigerant type and charge
   - SEER/EER rating if visible

6. EQUIPMENT TYPE: (Air Conditioner, Heat Pump, Furnace, Air Handler, Condenser, etc.)

Return as JSON. Use null for any field you cannot read clearly.
Include a confidence score (0-1) for the overall reading quality.
Also include the raw OCR text you can see."""
                    }
                ]
            }]
        )

        # Parse response
        result = self._parse_vision_response(response.content[0].text)

        # Validate against known patterns
        result = self._validate_identification(result)

        return result

    def _parse_vision_response(self, response_text: str) -> EquipmentIdentification:
        """Parse JSON response from vision model."""
        import json

        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return EquipmentIdentification(
                    brand=data.get("MANUFACTURER", "Unknown"),
                    model=data.get("MODEL NUMBER", ""),
                    serial=data.get("SERIAL NUMBER", ""),
                    manufacture_date=data.get("MANUFACTURE DATE", ""),
                    specs=data.get("SPECIFICATIONS", {}),
                    confidence=data.get("confidence", 0.5),
                    raw_text=data.get("raw_text", "")
                )
            except json.JSONDecodeError:
                pass

        return EquipmentIdentification(
            brand="Unknown", model="", serial="", manufacture_date="",
            specs={}, confidence=0.0, raw_text=response_text
        )

    def _validate_identification(self, ident: EquipmentIdentification) -> EquipmentIdentification:
        """Validate extracted data against known manufacturer patterns."""
        brand_lower = ident.brand.lower()

        if brand_lower in self.manufacturer_patterns:
            patterns = self.manufacturer_patterns[brand_lower]

            # Validate model number format
            if ident.model and not re.match(patterns["model_pattern"], ident.model, re.IGNORECASE):
                ident.confidence *= 0.7  # Reduce confidence if pattern doesn't match

            # Validate serial number format
            if ident.serial and not re.match(patterns["serial_pattern"], ident.serial):
                ident.confidence *= 0.8

        return ident
```

#### 3.2 Visual Problem Diagnosis

```python
# backend/services/vision/problem_analyzer.py

from dataclasses import dataclass
from anthropic import Anthropic
import base64

@dataclass
class VisualDiagnosis:
    identified_components: list[str]
    visible_issues: list[dict]
    suggested_causes: list[str]
    recommended_checks: list[str]
    matches_manual_patterns: list[dict]  # Cross-referenced with manuals
    confidence: float
    requires_physical_inspection: bool

class ProblemAnalyzer:
    """
    Analyze photos of HVAC equipment for visible issues.
    Cross-references visual findings with manual troubleshooting guides.
    """

    def __init__(self, anthropic_client: Anthropic, retriever: HVACRetriever):
        self.client = anthropic_client
        self.retriever = retriever

        # Known visual patterns for common issues
        self.visual_patterns = {
            "frozen_evaporator": {
                "visual_cues": ["ice buildup", "frost on coil", "frozen lines"],
                "related_issues": ["low refrigerant", "airflow restriction", "faulty TXV"]
            },
            "burnt_contactor": {
                "visual_cues": ["pitting on contacts", "discoloration", "melted plastic"],
                "related_issues": ["contactor failure", "high amp draw", "voltage issues"]
            },
            "capacitor_failure": {
                "visual_cues": ["bulging top", "oil leak", "rust"],
                "related_issues": ["capacitor failed", "motor not starting"]
            },
            "condenser_coil_blockage": {
                "visual_cues": ["debris buildup", "bent fins", "cottonwood"],
                "related_issues": ["high head pressure", "poor cooling", "compressor overheating"]
            },
            "refrigerant_leak": {
                "visual_cues": ["oil stains", "green residue", "frost at one point"],
                "related_issues": ["refrigerant leak", "low charge"]
            }
        }

    def analyze_problem_image(
        self,
        image: bytes,
        user_description: str,
        equipment_context: dict
    ) -> VisualDiagnosis:
        """
        Analyze image of potential problem area.
        Cross-references with manuals for equipment-specific guidance.
        """

        image_b64 = base64.standard_b64encode(image).decode("utf-8")

        # Step 1: Get visual analysis from Claude
        visual_analysis = self._get_visual_analysis(image_b64, user_description)

        # Step 2: Cross-reference with manuals
        manual_matches = self._cross_reference_manuals(
            visual_analysis,
            equipment_context
        )

        # Step 3: Build diagnosis
        diagnosis = self._build_diagnosis(visual_analysis, manual_matches)

        return diagnosis

    def _get_visual_analysis(self, image_b64: str, user_description: str) -> dict:
        """Use Claude vision to analyze the image."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": f"""Analyze this HVAC equipment image for potential issues.

Technician's description: "{user_description}"

Provide analysis in JSON format:

{{
    "components_visible": ["list of HVAC components you can identify"],
    "condition_observations": [
        {{
            "component": "component name",
            "observation": "what you see",
            "condition": "normal/worn/damaged/failed",
            "confidence": 0.0-1.0
        }}
    ],
    "potential_issues": [
        {{
            "issue": "description of potential problem",
            "visual_evidence": "what specifically indicates this",
            "severity": "low/medium/high/critical"
        }}
    ],
    "image_quality": "good/acceptable/poor",
    "needs_closer_look": ["list of components needing better photos"],
    "safety_concerns": ["any visible safety issues"]
}}

IMPORTANT:
- Only identify what you can clearly see
- Don't diagnose issues that aren't visually evident
- Note when you're uncertain
- Flag any safety concerns immediately"""
                    }
                ]
            }]
        )

        return self._parse_json_response(response.content[0].text)

    def _cross_reference_manuals(self, visual_analysis: dict, equipment: dict) -> list[dict]:
        """
        Cross-reference visual findings with manual troubleshooting guides.
        """
        matches = []

        for issue in visual_analysis.get("potential_issues", []):
            # Build search query from visual finding
            search_query = f"{issue['issue']} {issue.get('visual_evidence', '')}"

            # Add component context
            for component in visual_analysis.get("components_visible", []):
                if component.lower() in issue['issue'].lower():
                    search_query += f" {component}"

            # Search manuals
            from services.rag.query_processor import ProcessedQuery
            processed = ProcessedQuery(
                original=search_query,
                enhanced=search_query,
                intent="diagnose",
                equipment_hints={},
                urgency="routine"
            )

            results = self.retriever.retrieve(processed, equipment, top_k=3)

            if results.chunks:
                matches.append({
                    "visual_issue": issue["issue"],
                    "manual_references": [
                        {
                            "content": chunk["content"],
                            "source": chunk["metadata"].get("manual_title"),
                            "page": chunk["metadata"].get("page_numbers"),
                            "relevance": chunk["score"]
                        }
                        for chunk in results.chunks
                    ]
                })

        return matches

    def _build_diagnosis(self, visual: dict, manual_matches: list) -> VisualDiagnosis:
        """Combine visual analysis with manual information."""

        visible_issues = []
        suggested_causes = []
        recommended_checks = []

        for issue in visual.get("potential_issues", []):
            visible_issues.append({
                "description": issue["issue"],
                "evidence": issue.get("visual_evidence"),
                "severity": issue.get("severity", "medium")
            })

        for match in manual_matches:
            for ref in match.get("manual_references", []):
                # Extract causes and checks from manual content
                content = ref["content"].lower()
                if "cause" in content or "reason" in content:
                    suggested_causes.append(ref["content"][:200])
                if "check" in content or "inspect" in content or "verify" in content:
                    recommended_checks.append(ref["content"][:200])

        # Determine if physical inspection is needed
        requires_inspection = (
            visual.get("image_quality") == "poor" or
            len(visual.get("needs_closer_look", [])) > 0 or
            any(issue.get("confidence", 1) < 0.6 for issue in visual.get("condition_observations", []))
        )

        # Calculate overall confidence
        confidences = [obs.get("confidence", 0.5) for obs in visual.get("condition_observations", [])]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        return VisualDiagnosis(
            identified_components=visual.get("components_visible", []),
            visible_issues=visible_issues,
            suggested_causes=list(set(suggested_causes))[:5],
            recommended_checks=list(set(recommended_checks))[:5],
            matches_manual_patterns=manual_matches,
            confidence=avg_confidence,
            requires_physical_inspection=requires_inspection
        )

    def _parse_json_response(self, text: str) -> dict:
        """Safely parse JSON from Claude response."""
        import json
        import re

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}
```

---

## Feature 4: Anti-Hallucination Guardrails

### Purpose
Ensure all responses are factually grounded in manual content with clear attribution and appropriate uncertainty handling.

### Implementation

#### 4.1 Response Validator

```python
# backend/core/guardrails.py

from dataclasses import dataclass
from anthropic import Anthropic
from enum import Enum
import re

class ViolationType(Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    FABRICATED_SPEC = "fabricated_spec"
    MISSING_CITATION = "missing_citation"
    SAFETY_OMISSION = "safety_omission"
    CONTRADICTION = "contradiction"

@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[dict]
    corrected_response: str | None
    confidence_adjustment: float

class ResponseValidator:
    """
    Validates generated responses against source material.
    Catches and corrects potential hallucinations before delivery.
    """

    def __init__(self, anthropic_client: Anthropic):
        self.client = anthropic_client

        # Patterns that often indicate hallucination
        self.suspicious_patterns = [
            r"\d+\s*(?:psi|PSI)\b",  # Specific pressure readings
            r"\d+\s*(?:degrees?|°)\s*[FC]",  # Specific temperatures
            r"\d+\s*(?:amps?|A)\b",  # Specific amp readings
            r"\d+\s*(?:volts?|V)\b",  # Specific voltages
            r"\d+\s*(?:ohms?|Ω)\b",  # Specific resistance
            r"\d+\s*(?:lbs?|oz|ounces?)\s+(?:of\s+)?(?:refrigerant|R-?\d+)",  # Refrigerant amounts
            r"model\s+(?:number\s+)?[A-Z0-9-]+",  # Model numbers
            r"part\s+(?:number\s+)?[A-Z0-9-]+",  # Part numbers
        ]

    def validate(
        self,
        response: str,
        source_chunks: list[dict],
        query: str
    ) -> ValidationResult:
        """
        Validate response against source material.
        Returns validation result with any necessary corrections.
        """
        violations = []

        # Check 1: Verify all specific values appear in sources
        violations.extend(self._check_unsupported_values(response, source_chunks))

        # Check 2: Ensure citations are present and valid
        violations.extend(self._check_citations(response, source_chunks))

        # Check 3: Check for safety warning inclusion
        violations.extend(self._check_safety_warnings(response, source_chunks))

        # Check 4: Use Claude to verify factual grounding
        llm_violations = self._llm_validation(response, source_chunks, query)
        violations.extend(llm_violations)

        # Determine if correction is needed
        if violations:
            corrected = self._generate_correction(response, violations, source_chunks)
            confidence_adjustment = -0.1 * len(violations)
        else:
            corrected = None
            confidence_adjustment = 0

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            corrected_response=corrected,
            confidence_adjustment=confidence_adjustment
        )

    def _check_unsupported_values(self, response: str, sources: list[dict]) -> list[dict]:
        """Check if specific technical values in response exist in sources."""
        violations = []
        source_text = " ".join(s["content"] for s in sources)

        for pattern in self.suspicious_patterns:
            matches = re.finditer(pattern, response, re.IGNORECASE)
            for match in matches:
                value = match.group()
                # Check if this value exists in sources
                if value.lower() not in source_text.lower():
                    # Allow some flexibility for format differences
                    normalized = re.sub(r'\s+', '', value.lower())
                    if normalized not in re.sub(r'\s+', '', source_text.lower()):
                        violations.append({
                            "type": ViolationType.FABRICATED_SPEC,
                            "value": value,
                            "context": response[max(0, match.start()-30):match.end()+30],
                            "severity": "high"
                        })

        return violations

    def _check_citations(self, response: str, sources: list[dict]) -> list[dict]:
        """Verify citations are present and reference real sources."""
        violations = []

        # Check for citation presence
        citations = re.findall(r'\[Source (\d+)\]', response)

        if not citations and len(response) > 200:
            violations.append({
                "type": ViolationType.MISSING_CITATION,
                "message": "Response lacks source citations",
                "severity": "medium"
            })

        # Validate citation numbers
        for citation in citations:
            num = int(citation)
            if num < 1 or num > len(sources):
                violations.append({
                    "type": ViolationType.MISSING_CITATION,
                    "message": f"Invalid citation [Source {num}]",
                    "severity": "high"
                })

        return violations

    def _check_safety_warnings(self, response: str, sources: list[dict]) -> list[dict]:
        """Ensure relevant safety warnings from sources are included."""
        violations = []

        # Find safety content in sources
        safety_keywords = ["warning", "caution", "danger", "hazard", "safety"]
        source_safety = []

        for source in sources:
            content = source["content"].lower()
            if any(kw in content for kw in safety_keywords):
                source_safety.append(source["content"])

        # If sources contain safety info but response doesn't mention safety
        if source_safety:
            response_lower = response.lower()
            if not any(kw in response_lower for kw in safety_keywords):
                violations.append({
                    "type": ViolationType.SAFETY_OMISSION,
                    "message": "Source contains safety warnings not reflected in response",
                    "safety_content": source_safety[0][:200],
                    "severity": "high"
                })

        return violations

    def _llm_validation(self, response: str, sources: list[dict], query: str) -> list[dict]:
        """Use Claude to verify response is grounded in sources."""

        source_text = "\n---\n".join(s["content"] for s in sources)

        validation_prompt = f"""Verify if this response is factually grounded in the source material.

SOURCES:
{source_text}

RESPONSE TO VERIFY:
{response}

ORIGINAL QUESTION:
{query}

Check for:
1. Any claims not supported by the sources
2. Specific values (temperatures, pressures, amperages) that don't appear in sources
3. Procedures or steps not described in sources
4. Contradictions with source material

Return JSON:
{{
    "is_grounded": true/false,
    "ungrounded_claims": [
        {{
            "claim": "the specific claim",
            "issue": "why it's not grounded"
        }}
    ]
}}

Be strict - if a specific technical value isn't in the sources, flag it."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            temperature=0,
            messages=[{"role": "user", "content": validation_prompt}]
        )

        result = self._parse_json(response.content[0].text)

        violations = []
        for claim in result.get("ungrounded_claims", []):
            violations.append({
                "type": ViolationType.UNSUPPORTED_CLAIM,
                "claim": claim.get("claim"),
                "issue": claim.get("issue"),
                "severity": "medium"
            })

        return violations

    def _generate_correction(
        self,
        original: str,
        violations: list[dict],
        sources: list[dict]
    ) -> str:
        """Generate corrected response addressing violations."""

        violation_summary = "\n".join(
            f"- {v['type'].value}: {v.get('message', v.get('claim', v.get('value', '')))}"
            for v in violations
        )

        source_text = "\n---\n".join(s["content"] for s in sources)

        correction_prompt = f"""Correct this response to address the following issues:

ISSUES FOUND:
{violation_summary}

ORIGINAL RESPONSE:
{original}

AVAILABLE SOURCES:
{source_text}

Generate a corrected response that:
1. Removes or corrects any unsupported claims
2. Adds missing citations
3. Includes relevant safety warnings
4. Clearly states when information is not available

If a specific value was flagged as fabricated, either:
- Find the correct value in the sources and cite it
- Remove the claim and note the information isn't in the available sources"""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            temperature=0.1,
            messages=[{"role": "user", "content": correction_prompt}]
        )

        return response.content[0].text

    def _parse_json(self, text: str) -> dict:
        import json
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return {}


class ConfidenceScorer:
    """
    Calculate confidence scores for responses based on multiple factors.
    """

    def calculate_score(
        self,
        response: str,
        retrieval_scores: list[float],
        validation_result: ValidationResult,
        query_type: str
    ) -> float:
        """
        Calculate overall confidence score (0-1).

        Factors:
        - Retrieval relevance scores
        - Validation result
        - Query type (specs need higher confidence than general info)
        - Citation coverage
        """

        # Base score from retrieval
        if retrieval_scores:
            retrieval_score = sum(retrieval_scores) / len(retrieval_scores)
        else:
            retrieval_score = 0.0

        # Validation penalty
        validation_penalty = validation_result.confidence_adjustment

        # Citation coverage
        citation_count = len(re.findall(r'\[Source \d+\]', response))
        citation_score = min(1.0, citation_count / 3)  # At least 3 citations for full score

        # Query type modifier
        type_modifiers = {
            "find_spec": 0.9,  # Need high confidence for specs
            "understand_error": 0.85,
            "diagnose": 0.8,
            "general": 1.0
        }
        type_modifier = type_modifiers.get(query_type, 0.9)

        # Combine scores
        raw_score = (
            retrieval_score * 0.4 +
            citation_score * 0.3 +
            (1 if validation_result.is_valid else 0.5) * 0.3
        )

        final_score = (raw_score + validation_penalty) * type_modifier

        return max(0.0, min(1.0, final_score))
```

#### 4.2 Uncertainty Expression

```python
# backend/core/uncertainty.py

from dataclasses import dataclass
from enum import Enum

class UncertaintyLevel(Enum):
    CONFIDENT = "confident"
    PROBABLE = "probable"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"

@dataclass
class UncertaintyMarker:
    level: UncertaintyLevel
    reason: str
    alternative_actions: list[str]

class UncertaintyHandler:
    """
    Manage uncertainty expression in responses.
    Ensures appropriate hedging and escalation recommendations.
    """

    def get_uncertainty_prefix(self, confidence: float, context: dict) -> str:
        """Get appropriate uncertainty language for confidence level."""

        if confidence >= 0.85:
            return ""  # No hedging needed
        elif confidence >= 0.7:
            return "Based on the available manual information, "
        elif confidence >= 0.5:
            return "The manual suggests, though you should verify: "
        elif confidence >= 0.3:
            return "I found limited information on this. The manual indicates: "
        else:
            return "I don't have reliable information on this specific issue. "

    def get_escalation_recommendation(
        self,
        confidence: float,
        issue_severity: str,
        safety_related: bool
    ) -> str | None:
        """Determine if escalation to senior tech or manufacturer is needed."""

        # Always recommend escalation for safety issues with low confidence
        if safety_related and confidence < 0.7:
            return (
                "⚠️ This involves safety-critical components. "
                "Please consult with a senior technician or manufacturer "
                "technical support before proceeding."
            )

        # Recommend escalation for high-severity issues with medium confidence
        if issue_severity == "high" and confidence < 0.6:
            return (
                "This appears to be a complex issue. Consider consulting "
                "manufacturer technical support or a senior technician."
            )

        # Low confidence general recommendation
        if confidence < 0.4:
            return (
                "I couldn't find detailed information for this specific scenario. "
                "The manufacturer's technical support line may be helpful."
            )

        return None

    def add_uncertainty_markers(
        self,
        response: str,
        per_statement_confidence: list[dict]
    ) -> str:
        """Add inline uncertainty markers to specific statements."""

        # This would analyze individual statements and add markers
        # For simplicity, this is a placeholder

        markers = {
            "high": "",
            "medium": " (verify in manual)",
            "low": " (unconfirmed - check manual)"
        }

        # Apply markers to statements
        # Implementation would use NLP to identify claims and confidence

        return response
```

---

## Feature 5: API Layer

### Implementation

```python
# backend/api/routes.py

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import base64

app = FastAPI(title="HVAC AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response Models
class EquipmentContext(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    system_type: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    equipment: Optional[EquipmentContext] = None
    conversation_id: Optional[str] = None
    include_images: bool = False

class ChatResponse(BaseModel):
    answer: str
    confidence: str
    citations: list[dict]
    safety_warnings: list[str]
    suggested_followups: list[str]
    requires_escalation: bool
    conversation_id: str

class EquipmentScanResponse(BaseModel):
    brand: str
    model: str
    serial: str
    manufacture_date: str
    specs: dict
    confidence: float
    manuals_available: list[str]

class DiagnosisResponse(BaseModel):
    identified_components: list[str]
    visible_issues: list[dict]
    suggested_causes: list[str]
    recommended_checks: list[str]
    manual_references: list[dict]
    confidence: float
    requires_physical_inspection: bool

# Initialize services (would be done with dependency injection in production)
from services.rag.pipeline import RAGPipeline
from services.vision.nameplate_reader import NameplateReader
from services.vision.problem_analyzer import ProblemAnalyzer

rag_pipeline = RAGPipeline()
nameplate_reader = NameplateReader()
problem_analyzer = ProblemAnalyzer()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint for HVAC questions.
    Supports text queries with optional equipment context.
    """
    try:
        result = await rag_pipeline.process_query(
            query=request.message,
            equipment_context=request.equipment.dict() if request.equipment else {},
            conversation_id=request.conversation_id
        )

        return ChatResponse(
            answer=result.answer,
            confidence=result.confidence.value,
            citations=result.citations,
            safety_warnings=result.safety_warnings,
            suggested_followups=result.suggested_followups,
            requires_escalation=result.requires_escalation,
            conversation_id=result.conversation_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scan-equipment", response_model=EquipmentScanResponse)
async def scan_equipment(
    image: UploadFile = File(...),
):
    """
    Scan equipment nameplate to identify unit.
    Returns equipment info and available manuals.
    """
    try:
        image_bytes = await image.read()

        identification = nameplate_reader.read_nameplate(image_bytes)

        # Find available manuals for this equipment
        manuals = await find_manuals_for_equipment(
            identification.brand,
            identification.model
        )

        return EquipmentScanResponse(
            brand=identification.brand,
            model=identification.model,
            serial=identification.serial,
            manufacture_date=identification.manufacture_date,
            specs=identification.specs,
            confidence=identification.confidence,
            manuals_available=[m["title"] for m in manuals]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze-image", response_model=DiagnosisResponse)
async def analyze_problem_image(
    image: UploadFile = File(...),
    description: str = Form(...),
    equipment_brand: Optional[str] = Form(None),
    equipment_model: Optional[str] = Form(None),
):
    """
    Analyze photo of equipment for visible issues.
    Cross-references with manuals for equipment-specific guidance.
    """
    try:
        image_bytes = await image.read()

        equipment_context = {
            "brand": equipment_brand,
            "model": equipment_model
        }

        diagnosis = problem_analyzer.analyze_problem_image(
            image=image_bytes,
            user_description=description,
            equipment_context=equipment_context
        )

        return DiagnosisResponse(
            identified_components=diagnosis.identified_components,
            visible_issues=diagnosis.visible_issues,
            suggested_causes=diagnosis.suggested_causes,
            recommended_checks=diagnosis.recommended_checks,
            manual_references=[
                {
                    "issue": m["visual_issue"],
                    "references": m["manual_references"]
                }
                for m in diagnosis.matches_manual_patterns
            ],
            confidence=diagnosis.confidence,
            requires_physical_inspection=diagnosis.requires_physical_inspection
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/manuals")
async def list_manuals(
    brand: Optional[str] = None,
    model: Optional[str] = None,
    system_type: Optional[str] = None
):
    """List available manuals with optional filtering."""
    # Implementation to query manual database
    pass


@app.get("/api/manuals/{manual_id}/page/{page_number}")
async def get_manual_page(manual_id: str, page_number: int):
    """Get specific page from a manual (for citation linking)."""
    # Implementation to serve PDF page as image
    pass


@app.post("/api/feedback")
async def submit_feedback(
    conversation_id: str = Form(...),
    message_id: str = Form(...),
    feedback_type: str = Form(...),  # "helpful", "incorrect", "incomplete"
    details: Optional[str] = Form(None)
):
    """
    Submit feedback on AI response quality.
    Used to improve retrieval and response generation.
    """
    # Store feedback for analysis and model improvement
    pass


# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

---

## Feature 6: Frontend Implementation

### 6.1 Core Components

```typescript
// frontend/components/Chat/ChatInterface.tsx

import React, { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Message, EquipmentContext, ChatResponse } from '@/types';
import { chatApi } from '@/api/chat';
import { MessageBubble } from './MessageBubble';
import { EquipmentSelector } from '../Equipment/EquipmentSelector';
import { ImageCapture } from '../Camera/ImageCapture';
import { VoiceInput } from './VoiceInput';
import { SafetyWarning } from './SafetyWarning';

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [equipment, setEquipment] = useState<EquipmentContext | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showCamera, setShowCamera] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const chatMutation = useMutation({
    mutationFn: (message: string) => chatApi.sendMessage({
      message,
      equipment,
      conversationId,
    }),
    onSuccess: (response: ChatResponse) => {
      setConversationId(response.conversationId);

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        citations: response.citations,
        safetyWarnings: response.safetyWarnings,
        confidence: response.confidence,
        requiresEscalation: response.requiresEscalation,
        suggestedFollowups: response.suggestedFollowups,
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, assistantMessage]);
    },
  });

  const handleSend = () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    chatMutation.mutate(input);
    setInput('');
  };

  const handleImageCapture = async (imageBlob: Blob, type: 'equipment' | 'problem') => {
    if (type === 'equipment') {
      // Scan nameplate
      const result = await chatApi.scanEquipment(imageBlob);
      setEquipment({
        brand: result.brand,
        model: result.model,
        serial: result.serial,
      });

      // Add system message
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'system',
        content: `Equipment identified: ${result.brand} ${result.model}`,
        timestamp: new Date(),
      }]);
    } else {
      // Analyze problem image
      const description = input || 'Analyze this component';
      const result = await chatApi.analyzeImage(imageBlob, description, equipment);

      // Display diagnosis
      // ...
    }

    setShowCamera(false);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* Equipment Header */}
      <header className="bg-blue-600 text-white p-4">
        <EquipmentSelector
          value={equipment}
          onChange={setEquipment}
          onScanRequest={() => setShowCamera(true)}
        />
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map(message => (
          <MessageBubble
            key={message.id}
            message={message}
            onCitationClick={(citation) => {
              // Open manual viewer at cited page
            }}
            onFollowupClick={(question) => {
              setInput(question);
              handleSend();
            }}
          />
        ))}

        {chatMutation.isPending && (
          <div className="flex items-center space-x-2 text-gray-500">
            <div className="animate-pulse">Searching manuals...</div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t bg-white p-4">
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setShowCamera(true)}
            className="p-2 rounded-full bg-gray-100 hover:bg-gray-200"
            aria-label="Take photo"
          >
            📷
          </button>

          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Describe the issue..."
            className="flex-1 p-3 border rounded-lg focus:ring-2 focus:ring-blue-500"
          />

          <VoiceInput onTranscript={setInput} />

          <button
            onClick={handleSend}
            disabled={!input.trim() || chatMutation.isPending}
            className="p-3 bg-blue-600 text-white rounded-lg disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>

      {/* Camera Modal */}
      {showCamera && (
        <ImageCapture
          onCapture={handleImageCapture}
          onClose={() => setShowCamera(false)}
        />
      )}
    </div>
  );
}
```

```typescript
// frontend/components/Chat/MessageBubble.tsx

import React from 'react';
import { Message, Citation } from '@/types';
import { SafetyWarning } from './SafetyWarning';
import { ConfidenceBadge } from './ConfidenceBadge';

interface Props {
  message: Message;
  onCitationClick: (citation: Citation) => void;
  onFollowupClick: (question: string) => void;
}

export function MessageBubble({ message, onCitationClick, onFollowupClick }: Props) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-blue-600 text-white rounded-lg p-3 max-w-[80%]">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="bg-white rounded-lg shadow p-4 max-w-[90%] space-y-3">
        {/* Safety Warnings First */}
        {message.safetyWarnings?.map((warning, i) => (
          <SafetyWarning key={i} warning={warning} />
        ))}

        {/* Main Content */}
        <div className="prose prose-sm">
          {formatContentWithCitations(message.content, onCitationClick)}
        </div>

        {/* Confidence Indicator */}
        {message.confidence && (
          <ConfidenceBadge level={message.confidence} />
        )}

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="border-t pt-2 mt-2">
            <p className="text-xs text-gray-500 mb-1">Sources:</p>
            <div className="flex flex-wrap gap-1">
              {message.citations.map((citation, i) => (
                <button
                  key={i}
                  onClick={() => onCitationClick(citation)}
                  className="text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded hover:bg-blue-200"
                >
                  📖 {citation.manual}, p.{citation.page}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Escalation Warning */}
        {message.requiresEscalation && (
          <div className="bg-yellow-50 border border-yellow-200 rounded p-2 text-sm">
            ⚠️ Consider consulting senior tech or manufacturer support
          </div>
        )}

        {/* Follow-up Suggestions */}
        {message.suggestedFollowups && message.suggestedFollowups.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {message.suggestedFollowups.map((q, i) => (
              <button
                key={i}
                onClick={() => onFollowupClick(q)}
                className="text-xs bg-gray-100 px-2 py-1 rounded hover:bg-gray-200"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function formatContentWithCitations(
  content: string,
  onCitationClick: (citation: Citation) => void
): React.ReactNode {
  // Replace [Source N] with clickable links
  const parts = content.split(/(\[Source \d+\])/g);

  return parts.map((part, i) => {
    const match = part.match(/\[Source (\d+)\]/);
    if (match) {
      return (
        <button
          key={i}
          onClick={() => onCitationClick({ sourceNumber: parseInt(match[1]) })}
          className="text-blue-600 hover:underline"
        >
          {part}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
```

### 6.2 Offline Support (PWA)

```typescript
// frontend/hooks/useOfflineQueue.ts

import { useState, useEffect, useCallback } from 'react';
import { openDB, DBSchema, IDBPDatabase } from 'idb';

interface OfflineQueueDB extends DBSchema {
  pendingQueries: {
    key: string;
    value: {
      id: string;
      query: string;
      equipment: any;
      timestamp: number;
    };
  };
  cachedManuals: {
    key: string;
    value: {
      manualId: string;
      pages: ArrayBuffer[];
      metadata: any;
      cachedAt: number;
    };
  };
  cachedResponses: {
    key: string;
    value: {
      queryHash: string;
      response: any;
      cachedAt: number;
    };
  };
}

export function useOfflineQueue() {
  const [db, setDb] = useState<IDBPDatabase<OfflineQueueDB> | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    // Initialize IndexedDB
    const initDB = async () => {
      const database = await openDB<OfflineQueueDB>('hvac-assistant', 1, {
        upgrade(db) {
          db.createObjectStore('pendingQueries', { keyPath: 'id' });
          db.createObjectStore('cachedManuals', { keyPath: 'manualId' });
          db.createObjectStore('cachedResponses', { keyPath: 'queryHash' });
        },
      });
      setDb(database);
    };

    initDB();

    // Monitor online status
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Queue query for later when offline
  const queueQuery = useCallback(async (query: string, equipment: any) => {
    if (!db) return;

    const id = crypto.randomUUID();
    await db.add('pendingQueries', {
      id,
      query,
      equipment,
      timestamp: Date.now(),
    });

    setPendingCount(prev => prev + 1);

    return id;
  }, [db]);

  // Process queue when back online
  const processQueue = useCallback(async (sendMessage: (q: string, e: any) => Promise<any>) => {
    if (!db || !isOnline) return;

    const queries = await db.getAll('pendingQueries');

    for (const query of queries) {
      try {
        await sendMessage(query.query, query.equipment);
        await db.delete('pendingQueries', query.id);
        setPendingCount(prev => prev - 1);
      } catch (error) {
        console.error('Failed to process queued query:', error);
      }
    }
  }, [db, isOnline]);

  // Cache frequently-used manuals for offline access
  const cacheManual = useCallback(async (manualId: string, pages: ArrayBuffer[], metadata: any) => {
    if (!db) return;

    await db.put('cachedManuals', {
      manualId,
      pages,
      metadata,
      cachedAt: Date.now(),
    });
  }, [db]);

  // Get cached manual
  const getCachedManual = useCallback(async (manualId: string) => {
    if (!db) return null;
    return db.get('cachedManuals', manualId);
  }, [db]);

  // Cache response for common queries
  const cacheResponse = useCallback(async (query: string, equipment: any, response: any) => {
    if (!db) return;

    const queryHash = await hashQuery(query, equipment);
    await db.put('cachedResponses', {
      queryHash,
      response,
      cachedAt: Date.now(),
    });
  }, [db]);

  // Check for cached response
  const getCachedResponse = useCallback(async (query: string, equipment: any) => {
    if (!db) return null;

    const queryHash = await hashQuery(query, equipment);
    const cached = await db.get('cachedResponses', queryHash);

    // Only return if cached within last 24 hours
    if (cached && Date.now() - cached.cachedAt < 24 * 60 * 60 * 1000) {
      return cached.response;
    }

    return null;
  }, [db]);

  return {
    isOnline,
    pendingCount,
    queueQuery,
    processQueue,
    cacheManual,
    getCachedManual,
    cacheResponse,
    getCachedResponse,
  };
}

async function hashQuery(query: string, equipment: any): Promise<string> {
  const data = JSON.stringify({ query, equipment });
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(data));
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
```

```typescript
// frontend/sw.ts (Service Worker)

import { precacheAndRoute } from 'workbox-precaching';
import { registerRoute } from 'workbox-routing';
import { CacheFirst, NetworkFirst, StaleWhileRevalidate } from 'workbox-strategies';
import { ExpirationPlugin } from 'workbox-expiration';

declare const self: ServiceWorkerGlobalScope;

// Precache app shell
precacheAndRoute(self.__WB_MANIFEST);

// Cache API responses with network-first strategy
registerRoute(
  ({ url }) => url.pathname.startsWith('/api/'),
  new NetworkFirst({
    cacheName: 'api-cache',
    plugins: [
      new ExpirationPlugin({
        maxEntries: 100,
        maxAgeSeconds: 24 * 60 * 60, // 24 hours
      }),
    ],
  })
);

// Cache manual pages with cache-first (they don't change)
registerRoute(
  ({ url }) => url.pathname.includes('/manuals/') && url.pathname.includes('/page/'),
  new CacheFirst({
    cacheName: 'manual-pages',
    plugins: [
      new ExpirationPlugin({
        maxEntries: 500,
        maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days
      }),
    ],
  })
);

// Handle offline fallback
self.addEventListener('fetch', (event) => {
  if (!navigator.onLine) {
    // Return cached response or offline page
    event.respondWith(
      caches.match(event.request).then((response) => {
        return response || caches.match('/offline.html');
      })
    );
  }
});
```

---

## Feature 7: Voice Input for Hands-Free Operation

```typescript
// frontend/components/Chat/VoiceInput.tsx

import React, { useState, useRef, useCallback } from 'react';

interface Props {
  onTranscript: (text: string) => void;
}

export function VoiceInput({ onTranscript }: Props) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const startListening = useCallback(() => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Speech recognition not supported in this browser');
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();

    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    // Add HVAC terminology to grammar if supported
    if ('webkitSpeechGrammarList' in window) {
      const grammar = `
        #JSGF V1.0;
        grammar hvac;
        public <hvac_terms> = compressor | condenser | evaporator |
          refrigerant | thermostat | capacitor | contactor |
          blower | heat pump | air handler | superheat | subcooling |
          TXV | expansion valve | R410A | R22 | R134a;
      `;
      const speechGrammarList = new webkitSpeechGrammarList();
      speechGrammarList.addFromString(grammar, 1);
      recognition.grammars = speechGrammarList;
    }

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map(result => result[0].transcript)
        .join('');

      if (event.results[event.results.length - 1].isFinal) {
        onTranscript(transcript);
      }
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [onTranscript]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }, []);

  return (
    <button
      onClick={isListening ? stopListening : startListening}
      className={`p-2 rounded-full transition-colors ${
        isListening
          ? 'bg-red-500 text-white animate-pulse'
          : 'bg-gray-100 hover:bg-gray-200'
      }`}
      aria-label={isListening ? 'Stop listening' : 'Start voice input'}
    >
      🎤
    </button>
  );
}
```

---

## Deployment Architecture

```yaml
# infrastructure/docker-compose.yml

version: '3.8'

services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://api:8000
    depends_on:
      - api

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - VOYAGE_API_KEY=${VOYAGE_API_KEY}
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - REDIS_URL=redis://redis:6379
    depends_on:
      - qdrant
      - redis

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_storage:/qdrant/storage

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  ingestion-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - VOYAGE_API_KEY=${VOYAGE_API_KEY}
      - QDRANT_HOST=qdrant
      - S3_BUCKET=${S3_MANUAL_BUCKET}
    depends_on:
      - qdrant
      - redis

volumes:
  qdrant_storage:
  redis_data:
```

---

## Development Workflow: Local to Cloud Sync

### Purpose
Enable a development workflow where changes are made locally (adding books, tuning prompts, testing) and then synced to cloud when ready, while preserving existing cloud data.

### Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DEVELOPMENT CYCLE                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   LOCAL DEVELOPMENT                        CLOUD PRODUCTION              │
│   ┌─────────────────────┐                  ┌─────────────────────┐      │
│   │  • Add new books    │                  │  • Vercel (Frontend)│      │
│   │  • Tune prompts     │   migrate.sh     │  • Railway (Backend)│      │
│   │  • Test changes     │  ─────────────▶  │  • Qdrant Cloud     │      │
│   │  • Debug issues     │   (merge mode)   │  • Supabase (DB)    │      │
│   └─────────────────────┘                  └─────────────────────┘      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Migration Script

Located at `scripts/migrate-to-cloud.sh`:

```bash
# Check sync status (compare local vs cloud)
./scripts/migrate-to-cloud.sh status

# Sync new documents only (MERGE mode - default)
./scripts/migrate-to-cloud.sh all

# Sync only vectors (books/manuals)
./scripts/migrate-to-cloud.sh qdrant

# Sync only database (conversations/feedback)
./scripts/migrate-to-cloud.sh postgres

# Preview without making changes
./scripts/migrate-to-cloud.sh all --dry-run

# Full replace (destructive - use with caution!)
./scripts/migrate-to-cloud.sh all --replace
```

### Sync Modes

#### Merge Mode (Default)
- **Qdrant**: Compares document IDs, only uploads new documents
- **PostgreSQL**: Syncs conversations that don't exist in cloud
- **Cloud data preserved**: Existing cloud conversations/feedback NOT deleted

#### Replace Mode (`--replace`)
- **Full overwrite**: Replaces all cloud data with local
- **Use case**: Fresh start or complete reset
- **Caution**: Destructive operation, creates backup first

### Configuration

Create `.cloud-config` in project root:

```bash
# Qdrant Cloud (https://cloud.qdrant.io)
CLOUD_QDRANT_URL="https://your-cluster.us-east4-0.gcp.cloud.qdrant.io:6333"
CLOUD_QDRANT_API_KEY="your-api-key"

# PostgreSQL (Supabase, Railway, etc.)
CLOUD_POSTGRES_URL="postgresql://user:pass@host:5432/hvac_bot"

# Backup settings
BACKUP_DIR="./backups"
KEEP_BACKUPS=5
```

### What Gets Synced

| Component | Local | Cloud | Sync Behavior |
|-----------|-------|-------|---------------|
| **Qdrant Vectors** | localhost:6333 | Qdrant Cloud | New documents only (by document_id) |
| **PostgreSQL** | localhost:5432 | Supabase | New conversations only |
| **Redis** | localhost:6379 | Upstash | Not synced (session cache) |
| **Files** | data/manuals/ | N/A | Not synced (re-parseable) |

### Typical Development Cycle

```bash
# 1. Start local services
docker-compose up -d
cd backend && uvicorn main:app --reload

# 2. Make changes locally
#    - Upload new manuals via admin UI
#    - Tune prompts in generator.py
#    - Test chat responses
#    - Collect feedback

# 3. Check what would sync
./scripts/migrate-to-cloud.sh status
./scripts/migrate-to-cloud.sh all --dry-run

# 4. Sync to cloud
./scripts/migrate-to-cloud.sh all

# 5. Verify in production
#    - Test chat on production URL
#    - Check feedback stats
```

### Backup Strategy

The script automatically creates backups before sync:

```
backups/
├── hvac_manuals_20260127_143022.snapshot  # Qdrant snapshots
├── hvac_manuals_20260126_102315.snapshot
├── hvac_bot_20260127_143022.sql           # PostgreSQL dumps
├── cloud_backup_20260127_143022.sql       # Cloud backup (replace mode)
└── ...
```

Old backups are automatically cleaned up (keeps last 5 by default).

### Cloud Service Recommendations

| Service | Provider | Free Tier | Notes |
|---------|----------|-----------|-------|
| **Frontend** | Vercel | Unlimited | Auto-deploy on git push |
| **Backend** | Railway | $5/mo credit | Easy Docker deploy |
| **Qdrant** | Qdrant Cloud | 1GB | Managed vector DB |
| **PostgreSQL** | Supabase | 500MB | Managed Postgres |
| **Redis** | Upstash | 10K cmds/day | Optional (session cache) |

**Estimated monthly cost**: $0-30 for demo/light usage

---

## Summary

This implementation provides:

1. **Accurate, grounded responses** through multi-stage RAG with validation
2. **Image recognition** for equipment ID and visual diagnosis
3. **Strong anti-hallucination guardrails** with citation requirements and validation
4. **Mobile-first design** with offline support for field use
5. **Voice input** for hands-free operation
6. **Safety-first approach** with prominent warnings from manuals

The system prioritizes accuracy over creativity, ensuring technicians can trust the information provided while always having clear paths to escalate when confidence is low.

---

## Feature 8: Conversation Tracking & Analytics

### Purpose
Capture all conversations with rich metadata for analysis, fine-tuning data generation, and continuous improvement of RAG quality.

### 8.1 Database Schema

```sql
-- PostgreSQL schema for conversation tracking

-- Conversations table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    equipment_brand VARCHAR(100),
    equipment_model VARCHAR(100),
    equipment_serial VARCHAR(100),
    system_type VARCHAR(50),
    session_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    session_end TIMESTAMP WITH TIME ZONE,
    total_messages INT DEFAULT 0,
    resolution_status VARCHAR(20) DEFAULT 'ongoing', -- ongoing, resolved, escalated, abandoned
    user_satisfaction_score INT, -- 1-5 rating
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

-- Individual messages
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- user, assistant, system
    content TEXT NOT NULL,

    -- For assistant messages
    confidence_score FLOAT,
    confidence_level VARCHAR(20), -- high, medium, low, none
    retrieval_scores FLOAT[], -- scores of retrieved chunks
    cited_sources JSONB, -- [{manual_id, page, section}]
    safety_warnings TEXT[],
    required_escalation BOOLEAN DEFAULT FALSE,

    -- For user messages
    contains_image BOOLEAN DEFAULT FALSE,
    image_type VARCHAR(20), -- nameplate, problem, diagram
    detected_intent VARCHAR(50),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    response_time_ms INT, -- time to generate response

    -- Fine-tuning annotations (filled later)
    is_good_example BOOLEAN,
    annotation_notes TEXT,
    annotated_by UUID REFERENCES admin_users(id),
    annotated_at TIMESTAMP WITH TIME ZONE
);

-- Retrieved chunks for each assistant message
CREATE TABLE message_retrievals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
    chunk_id UUID, -- reference to vector store chunk
    chunk_content TEXT NOT NULL,
    chunk_metadata JSONB,
    similarity_score FLOAT NOT NULL,
    rerank_score FLOAT,
    was_used_in_response BOOLEAN DEFAULT TRUE,
    position_in_results INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User feedback on responses
CREATE TABLE message_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
    feedback_type VARCHAR(20) NOT NULL, -- helpful, incorrect, incomplete, unclear, outdated
    feedback_details TEXT,
    correct_answer TEXT, -- user-provided correct answer if available
    missing_information TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- RAG quality metrics (aggregated)
CREATE TABLE retrieval_quality_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    equipment_brand VARCHAR(100),
    equipment_model VARCHAR(100),
    query_intent VARCHAR(50),

    -- Metrics
    total_queries INT DEFAULT 0,
    avg_top_retrieval_score FLOAT,
    avg_response_confidence FLOAT,
    queries_with_no_results INT DEFAULT 0,
    queries_requiring_escalation INT DEFAULT 0,
    positive_feedback_count INT DEFAULT 0,
    negative_feedback_count INT DEFAULT 0,

    UNIQUE(date, equipment_brand, equipment_model, query_intent)
);

-- Knowledge gaps identified
CREATE TABLE knowledge_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_pattern TEXT NOT NULL,
    equipment_brand VARCHAR(100),
    equipment_model VARCHAR(100),
    occurrence_count INT DEFAULT 1,
    sample_queries TEXT[],
    avg_retrieval_score FLOAT,
    status VARCHAR(20) DEFAULT 'identified', -- identified, in_progress, resolved
    resolution_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_conversations_equipment ON conversations(equipment_brand, equipment_model);
CREATE INDEX idx_conversations_status ON conversations(resolution_status);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_confidence ON messages(confidence_level) WHERE role = 'assistant';
CREATE INDEX idx_message_feedback_type ON message_feedback(feedback_type);
CREATE INDEX idx_knowledge_gaps_status ON knowledge_gaps(status);
```

### 8.2 Conversation Tracker Service

```python
# backend/services/tracking/conversation_tracker.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

@dataclass
class TrackedMessage:
    id: str
    role: str
    content: str
    created_at: datetime

    # Assistant-specific
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    retrieval_scores: list[float] = field(default_factory=list)
    cited_sources: list[dict] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    required_escalation: bool = False
    response_time_ms: Optional[int] = None

    # User-specific
    contains_image: bool = False
    image_type: Optional[str] = None
    detected_intent: Optional[str] = None

@dataclass
class TrackedRetrieval:
    chunk_id: str
    chunk_content: str
    chunk_metadata: dict
    similarity_score: float
    rerank_score: Optional[float] = None
    was_used_in_response: bool = True
    position_in_results: int = 0

class ConversationTracker:
    """
    Tracks all conversations and messages for analytics and fine-tuning.
    Designed for minimal latency impact on main chat flow.
    """

    def __init__(self, db_session: AsyncSession, redis_client=None):
        self.db = db_session
        self.redis = redis_client  # For real-time metrics

    async def start_conversation(
        self,
        user_id: str,
        equipment_context: dict
    ) -> str:
        """Initialize a new conversation tracking session."""

        conversation_id = str(uuid.uuid4())

        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            equipment_brand=equipment_context.get('brand'),
            equipment_model=equipment_context.get('model'),
            equipment_serial=equipment_context.get('serial'),
            system_type=equipment_context.get('system_type'),
            metadata=json.dumps(equipment_context)
        )

        self.db.add(conversation)
        await self.db.commit()

        # Update real-time metrics
        if self.redis:
            await self.redis.incr('stats:conversations:today')
            if equipment_context.get('brand'):
                await self.redis.hincrby(
                    'stats:conversations:by_brand',
                    equipment_context['brand'],
                    1
                )

        return conversation_id

    async def track_message(
        self,
        conversation_id: str,
        message: TrackedMessage,
        retrievals: list[TrackedRetrieval] = None
    ) -> str:
        """Track a single message with optional retrieval data."""

        message_id = message.id or str(uuid.uuid4())

        # Insert message
        msg_record = Message(
            id=message_id,
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_level=message.confidence_level,
            retrieval_scores=message.retrieval_scores,
            cited_sources=json.dumps(message.cited_sources) if message.cited_sources else None,
            safety_warnings=message.safety_warnings,
            required_escalation=message.required_escalation,
            contains_image=message.contains_image,
            image_type=message.image_type,
            detected_intent=message.detected_intent,
            response_time_ms=message.response_time_ms,
            created_at=message.created_at
        )

        self.db.add(msg_record)

        # Insert retrieval data
        if retrievals:
            for i, ret in enumerate(retrievals):
                retrieval_record = MessageRetrieval(
                    id=str(uuid.uuid4()),
                    message_id=message_id,
                    chunk_id=ret.chunk_id,
                    chunk_content=ret.chunk_content,
                    chunk_metadata=json.dumps(ret.chunk_metadata),
                    similarity_score=ret.similarity_score,
                    rerank_score=ret.rerank_score,
                    was_used_in_response=ret.was_used_in_response,
                    position_in_results=i
                )
                self.db.add(retrieval_record)

        # Update conversation message count
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(total_messages=Conversation.total_messages + 1)
        )

        await self.db.commit()

        # Real-time metrics
        if self.redis and message.role == 'assistant':
            await self._update_realtime_metrics(message)

        return message_id

    async def track_feedback(
        self,
        message_id: str,
        feedback_type: str,
        details: str = None,
        correct_answer: str = None
    ):
        """Track user feedback on a response."""

        feedback = MessageFeedback(
            id=str(uuid.uuid4()),
            message_id=message_id,
            feedback_type=feedback_type,
            feedback_details=details,
            correct_answer=correct_answer
        )

        self.db.add(feedback)
        await self.db.commit()

        # Update metrics
        if self.redis:
            await self.redis.hincrby('stats:feedback:by_type', feedback_type, 1)

        # Auto-flag for review if negative feedback
        if feedback_type in ['incorrect', 'outdated']:
            await self._flag_for_review(message_id, feedback_type)

    async def end_conversation(
        self,
        conversation_id: str,
        resolution_status: str,
        satisfaction_score: int = None
    ):
        """Mark conversation as ended with resolution status."""

        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                session_end=datetime.utcnow(),
                resolution_status=resolution_status,
                user_satisfaction_score=satisfaction_score
            )
        )
        await self.db.commit()

    async def _update_realtime_metrics(self, message: TrackedMessage):
        """Update real-time metrics in Redis."""

        pipe = self.redis.pipeline()

        # Confidence distribution
        if message.confidence_level:
            pipe.hincrby('stats:confidence:distribution', message.confidence_level, 1)

        # Response time histogram
        if message.response_time_ms:
            bucket = self._get_latency_bucket(message.response_time_ms)
            pipe.hincrby('stats:latency:histogram', bucket, 1)

        # Escalation rate
        if message.required_escalation:
            pipe.incr('stats:escalations:today')

        await pipe.execute()

    async def _flag_for_review(self, message_id: str, reason: str):
        """Flag a message for manual review."""

        if self.redis:
            await self.redis.sadd('review:flagged_messages', message_id)
            await self.redis.hset(f'review:message:{message_id}', 'reason', reason)

    @staticmethod
    def _get_latency_bucket(ms: int) -> str:
        if ms < 500:
            return '<500ms'
        elif ms < 1000:
            return '500ms-1s'
        elif ms < 2000:
            return '1s-2s'
        elif ms < 5000:
            return '2s-5s'
        else:
            return '>5s'
```

### 8.3 Integration with Chat Pipeline

```python
# backend/services/rag/pipeline.py (updated)

import time
from services.tracking.conversation_tracker import (
    ConversationTracker, TrackedMessage, TrackedRetrieval
)

class RAGPipeline:
    """RAG pipeline with integrated conversation tracking."""

    def __init__(
        self,
        retriever: HVACRetriever,
        generator: GroundedGenerator,
        validator: ResponseValidator,
        tracker: ConversationTracker
    ):
        self.retriever = retriever
        self.generator = generator
        self.validator = validator
        self.tracker = tracker

    async def process_query(
        self,
        query: str,
        equipment_context: dict,
        conversation_id: str = None,
        user_id: str = None
    ) -> dict:
        """Process query with full tracking."""

        start_time = time.time()

        # Start conversation if new
        if not conversation_id:
            conversation_id = await self.tracker.start_conversation(
                user_id=user_id,
                equipment_context=equipment_context
            )

        # Track user message
        user_message = TrackedMessage(
            id=str(uuid.uuid4()),
            role='user',
            content=query,
            created_at=datetime.utcnow(),
            detected_intent=None  # Will be filled by query processor
        )

        # Process query
        processed_query = self.query_processor.process(query)
        user_message.detected_intent = processed_query.intent

        await self.tracker.track_message(conversation_id, user_message)

        # Retrieve
        retrieval_result = self.retriever.retrieve(
            processed_query,
            equipment_context
        )

        # Generate response
        response = self.generator.generate(
            query=query,
            retrieved_chunks=retrieval_result.chunks,
            equipment_context=equipment_context
        )

        # Validate
        validation = self.validator.validate(
            response.answer,
            retrieval_result.chunks,
            query
        )

        final_answer = validation.corrected_response or response.answer
        response_time_ms = int((time.time() - start_time) * 1000)

        # Track assistant message with retrievals
        assistant_message = TrackedMessage(
            id=str(uuid.uuid4()),
            role='assistant',
            content=final_answer,
            created_at=datetime.utcnow(),
            confidence_score=response.confidence.value if hasattr(response.confidence, 'value') else 0,
            confidence_level=response.confidence.name if hasattr(response.confidence, 'name') else 'unknown',
            retrieval_scores=[c['score'] for c in retrieval_result.chunks],
            cited_sources=response.citations,
            safety_warnings=response.safety_warnings,
            required_escalation=response.requires_escalation,
            response_time_ms=response_time_ms
        )

        tracked_retrievals = [
            TrackedRetrieval(
                chunk_id=chunk.get('id', str(uuid.uuid4())),
                chunk_content=chunk['content'],
                chunk_metadata=chunk['metadata'],
                similarity_score=chunk['score'],
                rerank_score=chunk.get('rerank_score'),
                was_used_in_response=True,
                position_in_results=i
            )
            for i, chunk in enumerate(retrieval_result.chunks)
        ]

        message_id = await self.tracker.track_message(
            conversation_id,
            assistant_message,
            tracked_retrievals
        )

        return {
            'answer': final_answer,
            'confidence': response.confidence,
            'citations': response.citations,
            'safety_warnings': response.safety_warnings,
            'suggested_followups': response.suggested_followups,
            'requires_escalation': response.requires_escalation,
            'conversation_id': conversation_id,
            'message_id': message_id  # For feedback tracking
        }
```

---

## Feature 9: Fine-Tuning Data Pipeline

### Purpose
Generate high-quality training data from conversations for fine-tuning embedding models, rerankers, and potentially the LLM itself.

### 9.1 Training Data Generator

```python
# backend/services/finetuning/data_generator.py

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generator
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

@dataclass
class EmbeddingTrainingPair:
    """Training pair for embedding model fine-tuning."""
    query: str
    positive_passage: str  # Relevant passage (high score, positive feedback)
    negative_passages: list[str]  # Irrelevant passages (low score or negative feedback)
    metadata: dict

@dataclass
class RerankerTrainingExample:
    """Training example for reranker fine-tuning."""
    query: str
    passages: list[str]
    relevance_scores: list[float]  # 0-1 relevance for each passage
    metadata: dict

@dataclass
class LLMTrainingExample:
    """Training example for LLM fine-tuning."""
    system_prompt: str
    user_message: str
    assistant_response: str
    sources_provided: list[str]
    equipment_context: dict
    quality_score: float  # Based on feedback and confidence

class TrainingDataGenerator:
    """
    Generate training data from tracked conversations.
    Filters for high-quality examples based on feedback and confidence.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def generate_embedding_pairs(
        self,
        min_confidence: float = 0.7,
        require_positive_feedback: bool = True,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Generator[EmbeddingTrainingPair, None, None]:
        """
        Generate query-passage pairs for embedding fine-tuning.

        Positive examples: High retrieval score + positive feedback
        Negative examples: Low retrieval score OR negative feedback
        """

        # Query for high-quality assistant messages
        query = select(Message).where(
            and_(
                Message.role == 'assistant',
                Message.confidence_score >= min_confidence
            )
        )

        if start_date:
            query = query.where(Message.created_at >= start_date)
        if end_date:
            query = query.where(Message.created_at <= end_date)

        result = await self.db.execute(query)
        messages = result.scalars().all()

        for message in messages:
            # Get user query (previous message)
            user_msg = await self._get_previous_user_message(message.conversation_id, message.created_at)
            if not user_msg:
                continue

            # Check feedback if required
            if require_positive_feedback:
                feedback = await self._get_message_feedback(message.id)
                if feedback and feedback.feedback_type in ['incorrect', 'incomplete']:
                    continue

            # Get retrievals
            retrievals = await self._get_message_retrievals(message.id)
            if not retrievals:
                continue

            # Split into positive and negative
            positive_passages = [
                r.chunk_content for r in retrievals
                if r.similarity_score >= 0.75 and r.was_used_in_response
            ]

            negative_passages = [
                r.chunk_content for r in retrievals
                if r.similarity_score < 0.5 or not r.was_used_in_response
            ]

            # Also add hard negatives from other equipment
            hard_negatives = await self._get_hard_negatives(
                user_msg.content,
                message.conversation_id
            )
            negative_passages.extend(hard_negatives[:3])

            if positive_passages:
                for positive in positive_passages:
                    yield EmbeddingTrainingPair(
                        query=user_msg.content,
                        positive_passage=positive,
                        negative_passages=negative_passages[:5],
                        metadata={
                            'conversation_id': message.conversation_id,
                            'confidence': message.confidence_score,
                            'equipment_brand': await self._get_equipment_brand(message.conversation_id)
                        }
                    )

    async def generate_reranker_examples(
        self,
        min_feedback_count: int = 0
    ) -> Generator[RerankerTrainingExample, None, None]:
        """
        Generate training examples for reranker fine-tuning.
        Uses feedback and citation data to determine relevance.
        """

        # Get messages with retrievals
        query = select(Message).where(
            and_(
                Message.role == 'assistant',
                Message.confidence_score.isnot(None)
            )
        ).order_by(Message.created_at.desc()).limit(10000)

        result = await self.db.execute(query)
        messages = result.scalars().all()

        for message in messages:
            user_msg = await self._get_previous_user_message(
                message.conversation_id,
                message.created_at
            )
            if not user_msg:
                continue

            retrievals = await self._get_message_retrievals(message.id)
            if len(retrievals) < 3:
                continue

            # Get citations to determine what was actually useful
            cited_chunks = set()
            if message.cited_sources:
                sources = json.loads(message.cited_sources)
                for source in sources:
                    cited_chunks.add(source.get('chunk_id'))

            # Calculate relevance scores
            passages = []
            scores = []

            for ret in retrievals:
                passages.append(ret.chunk_content)

                # Score based on: citation, position, similarity
                score = 0.0

                if ret.chunk_id in cited_chunks:
                    score += 0.5  # Cited in response

                if ret.was_used_in_response:
                    score += 0.3  # Used but maybe not cited

                # Boost by similarity score
                score += ret.similarity_score * 0.2

                scores.append(min(1.0, score))

            yield RerankerTrainingExample(
                query=user_msg.content,
                passages=passages,
                relevance_scores=scores,
                metadata={
                    'conversation_id': message.conversation_id,
                    'response_confidence': message.confidence_score
                }
            )

    async def generate_llm_examples(
        self,
        min_confidence: float = 0.8,
        require_positive_feedback: bool = True,
        exclude_escalations: bool = True
    ) -> Generator[LLMTrainingExample, None, None]:
        """
        Generate training examples for LLM fine-tuning.
        Only includes high-quality, verified responses.
        """

        # Get high-confidence messages
        conditions = [
            Message.role == 'assistant',
            Message.confidence_score >= min_confidence
        ]

        if exclude_escalations:
            conditions.append(Message.required_escalation == False)

        query = select(Message).where(and_(*conditions))
        result = await self.db.execute(query)
        messages = result.scalars().all()

        for message in messages:
            # Check feedback
            if require_positive_feedback:
                feedback = await self._get_message_feedback(message.id)
                if feedback and feedback.feedback_type == 'incorrect':
                    continue

            # Check for manual annotation
            if message.is_good_example == False:
                continue

            # Get context
            user_msg = await self._get_previous_user_message(
                message.conversation_id,
                message.created_at
            )
            if not user_msg:
                continue

            conversation = await self._get_conversation(message.conversation_id)
            retrievals = await self._get_message_retrievals(message.id)

            # Build training example
            system_prompt = self._build_system_prompt()
            sources = [r.chunk_content for r in retrievals if r.was_used_in_response]

            yield LLMTrainingExample(
                system_prompt=system_prompt,
                user_message=self._format_user_message(
                    user_msg.content,
                    sources,
                    {
                        'brand': conversation.equipment_brand,
                        'model': conversation.equipment_model
                    }
                ),
                assistant_response=message.content,
                sources_provided=sources,
                equipment_context={
                    'brand': conversation.equipment_brand,
                    'model': conversation.equipment_model,
                    'system_type': conversation.system_type
                },
                quality_score=message.confidence_score
            )

    async def _get_hard_negatives(self, query: str, exclude_conversation_id: str) -> list[str]:
        """Get passages from different equipment that match query but are wrong context."""

        # This would query the vector store for similar passages
        # but from different equipment brands/models
        # Implementation depends on vector store
        return []

    def _build_system_prompt(self) -> str:
        """Build the standard system prompt used during inference."""
        return """You are an HVAC technical assistant helping field technicians.
Your responses must be STRICTLY based on the provided manual excerpts.

CRITICAL RULES:
1. ONLY answer based on information in the provided sources
2. If the sources don't contain the answer, say "I don't have this information in the available manuals"
3. NEVER make up specifications, procedures, or troubleshooting steps
4. ALWAYS cite your sources using [Source X] notation
5. Prioritize safety - always include relevant warnings from the manuals"""

    def _format_user_message(
        self,
        query: str,
        sources: list[str],
        equipment: dict
    ) -> str:
        """Format user message with sources as it appears during inference."""
        formatted_sources = "\n---\n".join(
            f"[Source {i+1}]\n{source}"
            for i, source in enumerate(sources)
        )

        return f"""EQUIPMENT CONTEXT:
- Brand: {equipment.get('brand', 'Unknown')}
- Model: {equipment.get('model', 'Unknown')}

AVAILABLE SOURCES:
{formatted_sources}

TECHNICIAN'S QUESTION:
{query}"""


class TrainingDataExporter:
    """Export training data in various formats."""

    def __init__(self, generator: TrainingDataGenerator):
        self.generator = generator

    async def export_embedding_pairs_jsonl(
        self,
        output_path: str,
        **filter_kwargs
    ):
        """Export embedding pairs in JSONL format for sentence-transformers."""

        with open(output_path, 'w') as f:
            async for pair in self.generator.generate_embedding_pairs(**filter_kwargs):
                record = {
                    'query': pair.query,
                    'positive': pair.positive_passage,
                    'negatives': pair.negative_passages
                }
                f.write(json.dumps(record) + '\n')

    async def export_reranker_jsonl(
        self,
        output_path: str,
        **filter_kwargs
    ):
        """Export reranker examples in JSONL format."""

        with open(output_path, 'w') as f:
            async for example in self.generator.generate_reranker_examples(**filter_kwargs):
                for i, (passage, score) in enumerate(zip(example.passages, example.relevance_scores)):
                    record = {
                        'query': example.query,
                        'passage': passage,
                        'label': score
                    }
                    f.write(json.dumps(record) + '\n')

    async def export_llm_examples_jsonl(
        self,
        output_path: str,
        format: str = 'openai',  # or 'anthropic', 'alpaca'
        **filter_kwargs
    ):
        """Export LLM fine-tuning examples."""

        with open(output_path, 'w') as f:
            async for example in self.generator.generate_llm_examples(**filter_kwargs):
                if format == 'openai':
                    record = {
                        'messages': [
                            {'role': 'system', 'content': example.system_prompt},
                            {'role': 'user', 'content': example.user_message},
                            {'role': 'assistant', 'content': example.assistant_response}
                        ]
                    }
                elif format == 'anthropic':
                    record = {
                        'system': example.system_prompt,
                        'messages': [
                            {'role': 'user', 'content': example.user_message},
                            {'role': 'assistant', 'content': example.assistant_response}
                        ]
                    }
                elif format == 'alpaca':
                    record = {
                        'instruction': example.system_prompt,
                        'input': example.user_message,
                        'output': example.assistant_response
                    }

                f.write(json.dumps(record) + '\n')
```

### 9.2 Embedding Model Fine-Tuning

```python
# backend/services/finetuning/embedding_finetuner.py

from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader
import json

class EmbeddingFineTuner:
    """
    Fine-tune embedding model on HVAC-specific query-passage pairs.
    Uses contrastive learning with hard negatives.
    """

    def __init__(
        self,
        base_model: str = 'BAAI/bge-large-en-v1.5',
        output_dir: str = './models/hvac-embeddings'
    ):
        self.model = SentenceTransformer(base_model)
        self.output_dir = output_dir

    def load_training_data(self, jsonl_path: str) -> list[InputExample]:
        """Load training pairs from JSONL file."""

        examples = []

        with open(jsonl_path, 'r') as f:
            for line in f:
                data = json.loads(line)

                # Create training example with query, positive, and negatives
                example = InputExample(
                    texts=[
                        data['query'],
                        data['positive'],
                        *data['negatives'][:1]  # Use one hard negative
                    ]
                )
                examples.append(example)

        return examples

    def train(
        self,
        training_data_path: str,
        epochs: int = 3,
        batch_size: int = 16,
        warmup_steps: int = 100,
        learning_rate: float = 2e-5
    ):
        """Fine-tune the embedding model."""

        # Load data
        train_examples = self.load_training_data(training_data_path)
        train_dataloader = DataLoader(
            train_examples,
            shuffle=True,
            batch_size=batch_size
        )

        # Use Multiple Negatives Ranking Loss
        train_loss = losses.MultipleNegativesRankingLoss(self.model)

        # Train
        self.model.fit(
            train_objectives=[(train_dataloader, train_loss)],
            epochs=epochs,
            warmup_steps=warmup_steps,
            optimizer_params={'lr': learning_rate},
            output_path=self.output_dir,
            show_progress_bar=True
        )

        return self.output_dir

    def evaluate(self, test_data_path: str) -> dict:
        """Evaluate fine-tuned model on held-out test set."""

        from sentence_transformers import evaluation

        # Load test data
        queries = []
        corpus = {}
        relevant_docs = {}

        with open(test_data_path, 'r') as f:
            for i, line in enumerate(f):
                data = json.loads(line)
                query_id = f'q{i}'
                queries.append({'id': query_id, 'text': data['query']})

                # Add positive and negatives to corpus
                pos_id = f'd{i}_pos'
                corpus[pos_id] = data['positive']
                relevant_docs[query_id] = {pos_id}

                for j, neg in enumerate(data['negatives']):
                    neg_id = f'd{i}_neg{j}'
                    corpus[neg_id] = neg

        # Create evaluator
        evaluator = evaluation.InformationRetrievalEvaluator(
            queries={q['id']: q['text'] for q in queries},
            corpus=corpus,
            relevant_docs=relevant_docs,
            name='hvac-test'
        )

        # Evaluate
        results = evaluator(self.model)

        return {
            'mrr@10': results.get('hvac-test_mrr@10', 0),
            'ndcg@10': results.get('hvac-test_ndcg@10', 0),
            'recall@10': results.get('hvac-test_recall@10', 0)
        }
```

### 9.3 Reranker Fine-Tuning

```python
# backend/services/finetuning/reranker_finetuner.py

from sentence_transformers import CrossEncoder
import json
from torch.utils.data import Dataset, DataLoader
import torch

class RerankerDataset(Dataset):
    """Dataset for reranker training."""

    def __init__(self, data_path: str):
        self.examples = []

        with open(data_path, 'r') as f:
            for line in f:
                data = json.loads(line)
                self.examples.append({
                    'query': data['query'],
                    'passage': data['passage'],
                    'label': data['label']
                })

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        return self.examples[idx]

class RerankerFineTuner:
    """
    Fine-tune cross-encoder reranker on HVAC queries.
    """

    def __init__(
        self,
        base_model: str = 'cross-encoder/ms-marco-MiniLM-L-12-v2',
        output_dir: str = './models/hvac-reranker'
    ):
        self.model = CrossEncoder(base_model, num_labels=1)
        self.output_dir = output_dir

    def train(
        self,
        training_data_path: str,
        epochs: int = 3,
        batch_size: int = 32,
        learning_rate: float = 2e-5
    ):
        """Fine-tune the reranker."""

        # Load data
        train_samples = []

        with open(training_data_path, 'r') as f:
            for line in f:
                data = json.loads(line)
                train_samples.append([
                    [data['query'], data['passage']],
                    data['label']
                ])

        # Train
        self.model.fit(
            train_dataloader=DataLoader(
                train_samples,
                shuffle=True,
                batch_size=batch_size
            ),
            epochs=epochs,
            optimizer_params={'lr': learning_rate},
            output_path=self.output_dir
        )

        return self.output_dir

    def evaluate(self, test_data_path: str) -> dict:
        """Evaluate reranker on test set."""

        from sklearn.metrics import ndcg_score
        import numpy as np

        # Group by query
        query_data = {}

        with open(test_data_path, 'r') as f:
            for line in f:
                data = json.loads(line)
                query = data['query']

                if query not in query_data:
                    query_data[query] = {'passages': [], 'labels': []}

                query_data[query]['passages'].append(data['passage'])
                query_data[query]['labels'].append(data['label'])

        # Evaluate
        ndcg_scores = []

        for query, data in query_data.items():
            # Get model predictions
            pairs = [[query, p] for p in data['passages']]
            predictions = self.model.predict(pairs)

            # Calculate NDCG
            true_labels = np.array([data['labels']])
            pred_scores = np.array([predictions])

            ndcg = ndcg_score(true_labels, pred_scores)
            ndcg_scores.append(ndcg)

        return {
            'mean_ndcg': np.mean(ndcg_scores),
            'std_ndcg': np.std(ndcg_scores)
        }
```

---

## Feature 10: RAG Quality Analytics & Knowledge Gap Detection

### Purpose
Identify weak areas in the knowledge base and guide manual acquisition and processing priorities.

### 10.1 Analytics Service

```python
# backend/services/analytics/rag_analytics.py

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
import pandas as pd

@dataclass
class RetrievalQualityReport:
    period_start: datetime
    period_end: datetime
    total_queries: int
    avg_top_retrieval_score: float
    avg_response_confidence: float
    low_confidence_rate: float
    escalation_rate: float
    feedback_breakdown: dict
    worst_performing_equipment: list[dict]
    knowledge_gaps: list[dict]

@dataclass
class KnowledgeGap:
    query_pattern: str
    equipment_context: dict
    occurrence_count: int
    avg_retrieval_score: float
    sample_queries: list[str]
    suggested_action: str

class RAGAnalytics:
    """
    Analyze RAG performance and identify knowledge gaps.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def generate_quality_report(
        self,
        start_date: datetime,
        end_date: datetime,
        equipment_brand: str = None
    ) -> RetrievalQualityReport:
        """Generate comprehensive RAG quality report."""

        # Base query conditions
        conditions = [
            Message.role == 'assistant',
            Message.created_at >= start_date,
            Message.created_at <= end_date
        ]

        # Get basic metrics
        basic_stats = await self.db.execute(
            select(
                func.count(Message.id).label('total'),
                func.avg(Message.confidence_score).label('avg_confidence'),
                func.sum(case((Message.confidence_level == 'low', 1), else_=0)).label('low_confidence_count'),
                func.sum(case((Message.required_escalation == True, 1), else_=0)).label('escalation_count')
            ).where(and_(*conditions))
        )
        stats = basic_stats.fetchone()

        # Get average retrieval scores
        retrieval_stats = await self.db.execute(
            select(func.avg(MessageRetrieval.similarity_score))
            .join(Message)
            .where(
                and_(
                    Message.created_at >= start_date,
                    Message.created_at <= end_date,
                    MessageRetrieval.position_in_results == 0  # Top result
                )
            )
        )
        avg_retrieval = retrieval_stats.scalar() or 0

        # Feedback breakdown
        feedback_stats = await self.db.execute(
            select(
                MessageFeedback.feedback_type,
                func.count(MessageFeedback.id)
            )
            .join(Message)
            .where(
                and_(
                    Message.created_at >= start_date,
                    Message.created_at <= end_date
                )
            )
            .group_by(MessageFeedback.feedback_type)
        )
        feedback_breakdown = dict(feedback_stats.fetchall())

        # Worst performing equipment
        worst_equipment = await self._get_worst_performing_equipment(
            start_date, end_date
        )

        # Knowledge gaps
        gaps = await self._detect_knowledge_gaps(start_date, end_date)

        return RetrievalQualityReport(
            period_start=start_date,
            period_end=end_date,
            total_queries=stats.total or 0,
            avg_top_retrieval_score=avg_retrieval,
            avg_response_confidence=stats.avg_confidence or 0,
            low_confidence_rate=(stats.low_confidence_count or 0) / max(stats.total, 1),
            escalation_rate=(stats.escalation_count or 0) / max(stats.total, 1),
            feedback_breakdown=feedback_breakdown,
            worst_performing_equipment=worst_equipment,
            knowledge_gaps=gaps
        )

    async def _get_worst_performing_equipment(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10
    ) -> list[dict]:
        """Find equipment with lowest retrieval/confidence scores."""

        query = """
            SELECT
                c.equipment_brand,
                c.equipment_model,
                COUNT(m.id) as query_count,
                AVG(m.confidence_score) as avg_confidence,
                SUM(CASE WHEN m.confidence_level = 'low' THEN 1 ELSE 0 END) as low_confidence_count,
                SUM(CASE WHEN m.required_escalation THEN 1 ELSE 0 END) as escalation_count
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE m.role = 'assistant'
                AND m.created_at BETWEEN :start_date AND :end_date
                AND c.equipment_brand IS NOT NULL
            GROUP BY c.equipment_brand, c.equipment_model
            HAVING COUNT(m.id) >= 5
            ORDER BY avg_confidence ASC
            LIMIT :limit
        """

        result = await self.db.execute(
            query,
            {'start_date': start_date, 'end_date': end_date, 'limit': limit}
        )

        return [
            {
                'brand': row.equipment_brand,
                'model': row.equipment_model,
                'query_count': row.query_count,
                'avg_confidence': row.avg_confidence,
                'low_confidence_rate': row.low_confidence_count / row.query_count,
                'escalation_rate': row.escalation_count / row.query_count
            }
            for row in result.fetchall()
        ]

    async def _detect_knowledge_gaps(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> list[KnowledgeGap]:
        """
        Detect patterns where retrieval consistently fails.
        Uses clustering on low-confidence queries.
        """

        # Get low-confidence queries with context
        query = """
            SELECT
                m.id,
                m.content as query_text,
                m.confidence_score,
                m.detected_intent,
                c.equipment_brand,
                c.equipment_model,
                (
                    SELECT AVG(mr.similarity_score)
                    FROM message_retrievals mr
                    WHERE mr.message_id = m.id
                ) as avg_retrieval_score
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE m.role = 'user'
                AND m.created_at BETWEEN :start_date AND :end_date
                AND EXISTS (
                    SELECT 1 FROM messages m2
                    WHERE m2.conversation_id = m.conversation_id
                        AND m2.role = 'assistant'
                        AND m2.created_at > m.created_at
                        AND m2.confidence_level IN ('low', 'none')
                )
        """

        result = await self.db.execute(
            query,
            {'start_date': start_date, 'end_date': end_date}
        )
        low_confidence_queries = result.fetchall()

        # Cluster similar queries
        gaps = await self._cluster_queries(low_confidence_queries)

        return gaps

    async def _cluster_queries(self, queries: list) -> list[KnowledgeGap]:
        """Cluster similar queries to identify patterns."""

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import DBSCAN
        import numpy as np

        if len(queries) < 5:
            return []

        # Vectorize queries
        texts = [q.query_text for q in queries]
        vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        vectors = vectorizer.fit_transform(texts)

        # Cluster
        clustering = DBSCAN(eps=0.5, min_samples=3, metric='cosine')
        labels = clustering.fit_predict(vectors.toarray())

        # Analyze clusters
        gaps = []
        unique_labels = set(labels)
        unique_labels.discard(-1)  # Remove noise label

        for label in unique_labels:
            cluster_indices = np.where(labels == label)[0]
            cluster_queries = [queries[i] for i in cluster_indices]

            # Get common terms
            cluster_texts = [queries[i].query_text for i in cluster_indices]
            cluster_vectors = vectorizer.transform(cluster_texts)
            feature_names = vectorizer.get_feature_names_out()

            # Find top terms
            mean_vector = cluster_vectors.mean(axis=0).A1
            top_term_indices = mean_vector.argsort()[-5:][::-1]
            top_terms = [feature_names[i] for i in top_term_indices]

            # Get equipment context
            brands = [q.equipment_brand for q in cluster_queries if q.equipment_brand]
            models = [q.equipment_model for q in cluster_queries if q.equipment_model]

            # Calculate avg retrieval score
            avg_score = np.mean([
                q.avg_retrieval_score for q in cluster_queries
                if q.avg_retrieval_score
            ])

            gap = KnowledgeGap(
                query_pattern=" ".join(top_terms),
                equipment_context={
                    'brands': list(set(brands))[:5],
                    'models': list(set(models))[:5]
                },
                occurrence_count=len(cluster_queries),
                avg_retrieval_score=avg_score,
                sample_queries=[q.query_text for q in cluster_queries[:5]],
                suggested_action=self._suggest_action(top_terms, brands, avg_score)
            )
            gaps.append(gap)

        return sorted(gaps, key=lambda g: g.occurrence_count, reverse=True)

    def _suggest_action(
        self,
        terms: list[str],
        brands: list[str],
        avg_score: float
    ) -> str:
        """Suggest action to address knowledge gap."""

        if avg_score < 0.3:
            # Very low retrieval - likely missing manuals
            if brands:
                return f"Consider adding service manuals for: {', '.join(brands[:3])}"
            return "Consider expanding manual coverage for this topic"

        elif avg_score < 0.5:
            # Moderate retrieval - may need better chunking or terminology
            return f"Review chunking strategy for topics: {', '.join(terms[:3])}"

        else:
            # Decent retrieval but low confidence - may be LLM issue
            return "Review prompt engineering for this query pattern"


class KnowledgeGapTracker:
    """Track and manage knowledge gaps over time."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def record_gap(self, gap: KnowledgeGap):
        """Record or update a knowledge gap."""

        # Check if similar gap exists
        existing = await self.db.execute(
            select(KnowledgeGapRecord)
            .where(KnowledgeGapRecord.query_pattern == gap.query_pattern)
        )
        existing_gap = existing.scalar_one_or_none()

        if existing_gap:
            # Update existing
            existing_gap.occurrence_count += gap.occurrence_count
            existing_gap.sample_queries = list(set(
                existing_gap.sample_queries + gap.sample_queries
            ))[:10]
            existing_gap.avg_retrieval_score = (
                existing_gap.avg_retrieval_score + gap.avg_retrieval_score
            ) / 2
            existing_gap.updated_at = datetime.utcnow()
        else:
            # Create new
            new_gap = KnowledgeGapRecord(
                query_pattern=gap.query_pattern,
                equipment_brand=gap.equipment_context.get('brands', [None])[0],
                equipment_model=gap.equipment_context.get('models', [None])[0],
                occurrence_count=gap.occurrence_count,
                sample_queries=gap.sample_queries,
                avg_retrieval_score=gap.avg_retrieval_score,
                status='identified'
            )
            self.db.add(new_gap)

        await self.db.commit()

    async def mark_resolved(
        self,
        gap_id: str,
        resolution_notes: str
    ):
        """Mark a knowledge gap as resolved."""

        await self.db.execute(
            update(KnowledgeGapRecord)
            .where(KnowledgeGapRecord.id == gap_id)
            .values(
                status='resolved',
                resolution_notes=resolution_notes,
                updated_at=datetime.utcnow()
            )
        )
        await self.db.commit()

    async def get_priority_gaps(self, limit: int = 20) -> list[dict]:
        """Get knowledge gaps prioritized by impact."""

        result = await self.db.execute(
            select(KnowledgeGapRecord)
            .where(KnowledgeGapRecord.status != 'resolved')
            .order_by(
                KnowledgeGapRecord.occurrence_count.desc(),
                KnowledgeGapRecord.avg_retrieval_score.asc()
            )
            .limit(limit)
        )

        return [
            {
                'id': g.id,
                'pattern': g.query_pattern,
                'brand': g.equipment_brand,
                'model': g.equipment_model,
                'occurrences': g.occurrence_count,
                'avg_score': g.avg_retrieval_score,
                'samples': g.sample_queries[:3],
                'status': g.status
            }
            for g in result.scalars().all()
        ]
```

### 10.2 Internal Admin Dashboard API

```python
# backend/api/admin_routes.py

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
from services.analytics.rag_analytics import RAGAnalytics, KnowledgeGapTracker
from services.finetuning.data_generator import TrainingDataExporter

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/analytics/quality-report")
async def get_quality_report(
    days: int = 7,
    equipment_brand: str = None,
    analytics: RAGAnalytics = Depends(get_analytics_service)
):
    """Get RAG quality report for specified period."""

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    report = await analytics.generate_quality_report(
        start_date=start_date,
        end_date=end_date,
        equipment_brand=equipment_brand
    )

    return {
        'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
        'total_queries': report.total_queries,
        'avg_retrieval_score': round(report.avg_top_retrieval_score, 3),
        'avg_confidence': round(report.avg_response_confidence, 3),
        'low_confidence_rate': round(report.low_confidence_rate, 3),
        'escalation_rate': round(report.escalation_rate, 3),
        'feedback': report.feedback_breakdown,
        'worst_equipment': report.worst_performing_equipment,
        'knowledge_gaps': [
            {
                'pattern': g.query_pattern,
                'equipment': g.equipment_context,
                'count': g.occurrence_count,
                'avg_score': round(g.avg_retrieval_score, 3),
                'samples': g.sample_queries,
                'action': g.suggested_action
            }
            for g in report.knowledge_gaps[:10]
        ]
    }

@router.get("/analytics/knowledge-gaps")
async def get_knowledge_gaps(
    status: str = None,
    limit: int = 20,
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker)
):
    """Get prioritized list of knowledge gaps."""

    gaps = await tracker.get_priority_gaps(limit=limit)

    if status:
        gaps = [g for g in gaps if g['status'] == status]

    return {'gaps': gaps}

@router.post("/analytics/knowledge-gaps/{gap_id}/resolve")
async def resolve_knowledge_gap(
    gap_id: str,
    resolution_notes: str,
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker)
):
    """Mark a knowledge gap as resolved."""

    await tracker.mark_resolved(gap_id, resolution_notes)
    return {'status': 'resolved'}

@router.get("/analytics/equipment-coverage")
async def get_equipment_coverage(
    db: AsyncSession = Depends(get_db)
):
    """Analyze manual coverage by equipment brand/model."""

    # Get unique equipment from conversations
    conv_equipment = await db.execute("""
        SELECT DISTINCT equipment_brand, equipment_model
        FROM conversations
        WHERE equipment_brand IS NOT NULL
    """)

    # Get equipment covered by manuals
    manual_equipment = await db.execute("""
        SELECT DISTINCT brand, model
        FROM manual_metadata
    """)

    conv_set = {(r[0], r[1]) for r in conv_equipment.fetchall()}
    manual_set = {(r[0], r[1]) for r in manual_equipment.fetchall()}

    # Find gaps
    missing_coverage = conv_set - manual_set

    return {
        'total_equipment_seen': len(conv_set),
        'equipment_with_manuals': len(conv_set & manual_set),
        'equipment_without_manuals': len(missing_coverage),
        'missing_coverage': [
            {'brand': b, 'model': m}
            for b, m in sorted(missing_coverage)
        ][:50]
    }

@router.post("/finetuning/export/embeddings")
async def export_embedding_training_data(
    min_confidence: float = 0.7,
    require_positive_feedback: bool = True,
    exporter: TrainingDataExporter = Depends(get_exporter)
):
    """Export training data for embedding model fine-tuning."""

    output_path = f"/tmp/embedding_training_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"

    await exporter.export_embedding_pairs_jsonl(
        output_path=output_path,
        min_confidence=min_confidence,
        require_positive_feedback=require_positive_feedback
    )

    # Return download URL or S3 path
    return {'export_path': output_path}

@router.post("/finetuning/export/reranker")
async def export_reranker_training_data(
    exporter: TrainingDataExporter = Depends(get_exporter)
):
    """Export training data for reranker fine-tuning."""

    output_path = f"/tmp/reranker_training_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"

    await exporter.export_reranker_jsonl(output_path=output_path)

    return {'export_path': output_path}

@router.post("/finetuning/export/llm")
async def export_llm_training_data(
    format: str = 'openai',
    min_confidence: float = 0.8,
    exporter: TrainingDataExporter = Depends(get_exporter)
):
    """Export training data for LLM fine-tuning."""

    output_path = f"/tmp/llm_training_{format}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"

    await exporter.export_llm_examples_jsonl(
        output_path=output_path,
        format=format,
        min_confidence=min_confidence
    )

    return {'export_path': output_path}

@router.get("/conversations/flagged")
async def get_flagged_conversations(
    limit: int = 50,
    redis = Depends(get_redis)
):
    """Get conversations flagged for review."""

    flagged_ids = await redis.smembers('review:flagged_messages')

    flagged = []
    for msg_id in list(flagged_ids)[:limit]:
        reason = await redis.hget(f'review:message:{msg_id}', 'reason')
        flagged.append({
            'message_id': msg_id,
            'flag_reason': reason
        })

    return {'flagged_messages': flagged}

@router.post("/conversations/{message_id}/annotate")
async def annotate_message(
    message_id: str,
    is_good_example: bool,
    notes: str = None,
    admin_user_id: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Annotate a message for training data quality."""

    await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(
            is_good_example=is_good_example,
            annotation_notes=notes,
            annotated_by=admin_user_id,
            annotated_at=datetime.utcnow()
        )
    )
    await db.commit()

    return {'status': 'annotated'}

@router.get("/realtime/metrics")
async def get_realtime_metrics(
    redis = Depends(get_redis)
):
    """Get real-time system metrics from Redis."""

    pipe = redis.pipeline()
    pipe.get('stats:conversations:today')
    pipe.hgetall('stats:confidence:distribution')
    pipe.hgetall('stats:latency:histogram')
    pipe.get('stats:escalations:today')
    pipe.hgetall('stats:feedback:by_type')

    results = await pipe.execute()

    return {
        'conversations_today': int(results[0] or 0),
        'confidence_distribution': results[1] or {},
        'latency_histogram': results[2] or {},
        'escalations_today': int(results[3] or 0),
        'feedback_by_type': results[4] or {}
    }
```

---

## Feature 11: A/B Testing Framework for RAG

### Purpose
Test different retrieval strategies, prompts, and model configurations.

```python
# backend/services/experiments/ab_testing.py

from dataclasses import dataclass
from typing import Callable, Any
import random
import hashlib
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass
class Experiment:
    id: str
    name: str
    description: str
    variants: dict[str, dict]  # variant_name -> config
    traffic_allocation: dict[str, float]  # variant_name -> percentage (0-1)
    start_date: datetime
    end_date: datetime | None
    is_active: bool = True

@dataclass
class ExperimentAssignment:
    experiment_id: str
    variant_name: str
    config: dict

class ABTestingService:
    """
    A/B testing framework for RAG experiments.
    Supports testing different:
    - Embedding models
    - Retrieval strategies
    - Reranking approaches
    - Prompt variations
    - Chunk sizes
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.experiments: dict[str, Experiment] = {}

    async def load_active_experiments(self):
        """Load active experiments from database."""

        result = await self.db.execute(
            select(ExperimentRecord)
            .where(ExperimentRecord.is_active == True)
        )

        for record in result.scalars().all():
            self.experiments[record.id] = Experiment(
                id=record.id,
                name=record.name,
                description=record.description,
                variants=record.variants,
                traffic_allocation=record.traffic_allocation,
                start_date=record.start_date,
                end_date=record.end_date,
                is_active=record.is_active
            )

    def get_assignment(
        self,
        experiment_id: str,
        user_id: str
    ) -> ExperimentAssignment | None:
        """Get deterministic experiment assignment for a user."""

        experiment = self.experiments.get(experiment_id)
        if not experiment or not experiment.is_active:
            return None

        # Deterministic assignment based on user_id
        hash_input = f"{experiment_id}:{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        assignment_value = (hash_value % 10000) / 10000  # 0-1 range

        # Determine variant based on traffic allocation
        cumulative = 0
        for variant_name, allocation in experiment.traffic_allocation.items():
            cumulative += allocation
            if assignment_value < cumulative:
                return ExperimentAssignment(
                    experiment_id=experiment_id,
                    variant_name=variant_name,
                    config=experiment.variants[variant_name]
                )

        # Fallback to first variant
        first_variant = list(experiment.variants.keys())[0]
        return ExperimentAssignment(
            experiment_id=experiment_id,
            variant_name=first_variant,
            config=experiment.variants[first_variant]
        )

    async def record_exposure(
        self,
        experiment_id: str,
        variant_name: str,
        user_id: str,
        conversation_id: str
    ):
        """Record that a user was exposed to a variant."""

        exposure = ExperimentExposure(
            experiment_id=experiment_id,
            variant_name=variant_name,
            user_id=user_id,
            conversation_id=conversation_id,
            exposed_at=datetime.utcnow()
        )

        self.db.add(exposure)
        await self.db.commit()

    async def record_outcome(
        self,
        experiment_id: str,
        variant_name: str,
        conversation_id: str,
        metrics: dict
    ):
        """Record outcome metrics for an exposure."""

        outcome = ExperimentOutcome(
            experiment_id=experiment_id,
            variant_name=variant_name,
            conversation_id=conversation_id,
            metrics=metrics,
            recorded_at=datetime.utcnow()
        )

        self.db.add(outcome)
        await self.db.commit()

    async def get_experiment_results(
        self,
        experiment_id: str
    ) -> dict:
        """Calculate experiment results with statistical significance."""

        from scipy import stats
        import numpy as np

        # Get outcomes by variant
        outcomes = await self.db.execute(
            select(ExperimentOutcome)
            .where(ExperimentOutcome.experiment_id == experiment_id)
        )

        variant_metrics = {}
        for outcome in outcomes.scalars().all():
            if outcome.variant_name not in variant_metrics:
                variant_metrics[outcome.variant_name] = {
                    'confidence_scores': [],
                    'retrieval_scores': [],
                    'feedback_positive': 0,
                    'feedback_total': 0,
                    'response_times': []
                }

            vm = variant_metrics[outcome.variant_name]
            metrics = outcome.metrics

            if metrics.get('confidence_score'):
                vm['confidence_scores'].append(metrics['confidence_score'])
            if metrics.get('top_retrieval_score'):
                vm['retrieval_scores'].append(metrics['top_retrieval_score'])
            if metrics.get('response_time_ms'):
                vm['response_times'].append(metrics['response_time_ms'])
            if metrics.get('feedback_type'):
                vm['feedback_total'] += 1
                if metrics['feedback_type'] == 'helpful':
                    vm['feedback_positive'] += 1

        # Calculate statistics
        results = {}
        variant_names = list(variant_metrics.keys())

        if len(variant_names) < 2:
            return {'error': 'Need at least 2 variants for comparison'}

        control = variant_names[0]

        for variant in variant_names:
            vm = variant_metrics[variant]

            results[variant] = {
                'sample_size': len(vm['confidence_scores']),
                'avg_confidence': np.mean(vm['confidence_scores']) if vm['confidence_scores'] else 0,
                'avg_retrieval_score': np.mean(vm['retrieval_scores']) if vm['retrieval_scores'] else 0,
                'avg_response_time_ms': np.mean(vm['response_times']) if vm['response_times'] else 0,
                'positive_feedback_rate': vm['feedback_positive'] / max(vm['feedback_total'], 1)
            }

            # Statistical significance vs control
            if variant != control and vm['confidence_scores']:
                control_scores = variant_metrics[control]['confidence_scores']
                if control_scores:
                    t_stat, p_value = stats.ttest_ind(
                        vm['confidence_scores'],
                        control_scores
                    )
                    results[variant]['vs_control'] = {
                        't_statistic': t_stat,
                        'p_value': p_value,
                        'significant': p_value < 0.05
                    }

        return {
            'experiment_id': experiment_id,
            'variants': results,
            'control_variant': control,
            'recommendation': self._get_recommendation(results, control)
        }

    def _get_recommendation(self, results: dict, control: str) -> str:
        """Generate recommendation based on results."""

        best_variant = control
        best_confidence = results[control]['avg_confidence']

        for variant, data in results.items():
            if variant == control:
                continue

            if (data.get('vs_control', {}).get('significant') and
                data['avg_confidence'] > best_confidence):
                best_variant = variant
                best_confidence = data['avg_confidence']

        if best_variant == control:
            return f"No variant outperforms control. Keep current configuration."
        else:
            improvement = (best_confidence - results[control]['avg_confidence']) / results[control]['avg_confidence'] * 100
            return f"Variant '{best_variant}' shows {improvement:.1f}% improvement. Consider promoting to production."


# Example experiment configuration
EXAMPLE_EXPERIMENTS = {
    'embedding_model_comparison': Experiment(
        id='exp_embed_001',
        name='Embedding Model Comparison',
        description='Compare BGE-large vs Voyage-2 for HVAC retrieval',
        variants={
            'bge_large': {
                'embedding_model': 'BAAI/bge-large-en-v1.5',
                'embedding_dim': 1024
            },
            'voyage_2': {
                'embedding_model': 'voyage-large-2',
                'embedding_dim': 1024
            }
        },
        traffic_allocation={'bge_large': 0.5, 'voyage_2': 0.5},
        start_date=datetime(2024, 1, 1),
        end_date=None
    ),

    'chunk_size_test': Experiment(
        id='exp_chunk_001',
        name='Chunk Size Optimization',
        description='Test different chunk sizes for troubleshooting sections',
        variants={
            'small_chunks': {'max_chunk_size': 500, 'overlap': 50},
            'medium_chunks': {'max_chunk_size': 1000, 'overlap': 100},
            'large_chunks': {'max_chunk_size': 2000, 'overlap': 200}
        },
        traffic_allocation={
            'small_chunks': 0.33,
            'medium_chunks': 0.34,
            'large_chunks': 0.33
        },
        start_date=datetime(2024, 1, 1),
        end_date=None
    ),

    'prompt_variation': Experiment(
        id='exp_prompt_001',
        name='System Prompt Variation',
        description='Test different prompt styles for grounded responses',
        variants={
            'strict': {
                'system_prompt': 'You must ONLY use information from the provided sources...'
            },
            'balanced': {
                'system_prompt': 'Answer based on the provided sources. If unsure...'
            }
        },
        traffic_allocation={'strict': 0.5, 'balanced': 0.5},
        start_date=datetime(2024, 1, 1),
        end_date=None
    )
}
```

---

## Summary: Data-Driven Improvement Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTINUOUS IMPROVEMENT LOOP                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. TRACK: Every conversation, retrieval, and response         │
│     - Store queries, retrievals, responses, feedback           │
│     - Capture confidence scores and citations                  │
│     - Record user feedback (helpful/incorrect/incomplete)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. ANALYZE: Identify patterns and gaps                        │
│     - Generate quality reports by equipment/time               │
│     - Cluster low-confidence queries to find knowledge gaps    │
│     - Track which manuals are missing                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. IMPROVE: Fine-tune and experiment                          │
│     - Export high-quality examples for fine-tuning             │
│     - Fine-tune embeddings on HVAC query-passage pairs         │
│     - Fine-tune reranker on relevance judgments                │
│     - A/B test retrieval strategies and prompts                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. EXPAND: Fill knowledge gaps                                │
│     - Prioritize manual acquisition by gap frequency           │
│     - Re-chunk problematic sections                            │
│     - Add missing equipment coverage                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              └──────────────► (back to TRACK)
```

This creates a flywheel where:
- More usage → Better training data
- Better training → Higher accuracy
- Higher accuracy → More user trust
- More trust → More usage
