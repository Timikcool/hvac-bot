# Vertex AI Integration

The HVAC AI Assistant supports Google Vertex AI as an alternative to the custom RAG pipeline. This provides a fully managed solution for document parsing, embeddings, vector search, and grounded generation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PROVIDER OPTIONS                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  CUSTOM (Default)                  VERTEX AI (Managed)              │
│  ─────────────────                 ───────────────────              │
│                                                                     │
│  ┌─────────────┐                   ┌─────────────────┐              │
│  │ OpenAI      │                   │ Vertex AI       │              │
│  │ Embeddings  │                   │ Embeddings      │              │
│  │ (1536 dim)  │                   │ (768 dim)       │              │
│  └─────────────┘                   └─────────────────┘              │
│         │                                   │                       │
│         ▼                                   ▼                       │
│  ┌─────────────┐                   ┌─────────────────┐              │
│  │ Qdrant      │                   │ Vector Search   │              │
│  │ (self-host) │                   │ (managed)       │              │
│  └─────────────┘                   └─────────────────┘              │
│         │                                   │                       │
│         ▼                                   ▼                       │
│  ┌─────────────┐                   ┌─────────────────┐              │
│  │ Claude +    │                   │ Gemini +        │              │
│  │ Custom RAG  │                   │ RAG Engine      │              │
│  └─────────────┘                   └─────────────────┘              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Document AI Parser

**Purpose:** Parse PDF documents with native support for tables, forms, and layouts.

**Location:** `backend/services/gcp/document_ai.py`

**Features:**
- Native PDF parsing (no image conversion needed)
- Built-in table extraction
- Form field detection
- Layout preservation
- No content filtering issues

### 2. Vertex AI Embeddings

**Purpose:** Generate text embeddings using Google's text-embedding-004 model.

**Location:** `backend/services/gcp/embeddings.py`

**Features:**
- 768-dimensional embeddings
- Optimized for retrieval tasks (RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY)
- Batch processing up to 250 texts
- Integrated with Vertex AI

### 3. Vertex AI Vector Search

**Purpose:** Managed vector database for similarity search.

**Location:** `backend/services/gcp/vector_search.py`

**Features:**
- Scalable approximate nearest neighbor (ANN) search
- Streaming updates
- Managed infrastructure
- High availability

### 4. Vertex AI RAG Engine

**Purpose:** Fully managed RAG pipeline with grounded generation.

**Location:** `backend/services/gcp/rag_engine.py`

**Features:**
- Automatic document ingestion
- Built-in chunking and embedding
- Grounded retrieval with Gemini
- Citation extraction
- Corpus management

## Configuration

### Environment Variables

```bash
# Google Cloud Platform
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
GCP_CREDENTIALS_PATH=/path/to/service-account.json

# Document AI
DOCUMENT_AI_PROCESSOR_ID=your-processor-id

# Vertex AI Embeddings
VERTEX_EMBEDDING_MODEL=text-embedding-004

# Vertex AI Vector Search
VERTEX_INDEX_ENDPOINT_ID=your-endpoint-id
VERTEX_DEPLOYED_INDEX_ID=your-index-id

# Vertex AI RAG Engine
VERTEX_RAG_CORPUS=projects/your-project/locations/us-central1/ragCorpora/your-corpus

# Provider Selection
EMBEDDING_PROVIDER=auto      # openai, vertex, or auto
VECTOR_STORE_PROVIDER=qdrant # qdrant or vertex
RAG_PROVIDER=custom          # custom or vertex
```

### Provider Selection

| Setting | Options | Description |
|---------|---------|-------------|
| `EMBEDDING_PROVIDER` | `auto`, `openai`, `vertex` | Embedding provider. `auto` tries Vertex first. |
| `VECTOR_STORE_PROVIDER` | `qdrant`, `vertex` | Vector database provider. |
| `RAG_PROVIDER` | `custom`, `vertex` | RAG pipeline provider. |

## Setup Guide

### Step 1: Create GCP Project

```bash
# Create project
gcloud projects create hvac-ai-assistant

# Enable APIs
gcloud services enable aiplatform.googleapis.com
gcloud services enable documentai.googleapis.com
```

### Step 2: Create Service Account

```bash
# Create service account
gcloud iam service-accounts create hvac-assistant \
    --display-name="HVAC AI Assistant"

# Grant roles
gcloud projects add-iam-policy-binding hvac-ai-assistant \
    --member="serviceAccount:hvac-assistant@hvac-ai-assistant.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Create key
gcloud iam service-accounts keys create service-account.json \
    --iam-account=hvac-assistant@hvac-ai-assistant.iam.gserviceaccount.com
```

### Step 3: Set Up Document AI

```bash
# Create Document AI processor (via Cloud Console)
# 1. Go to Document AI in Cloud Console
# 2. Create a new processor (Document OCR)
# 3. Note the processor ID
```

### Step 4: Set Up Vector Search

```bash
# Create index (via Cloud Console or API)
from google.cloud import aiplatform

aiplatform.init(project="hvac-ai-assistant", location="us-central1")

# Create index
index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
    display_name="hvac-manuals-index",
    dimensions=768,  # Vertex AI embedding dimension
    approximate_neighbors_count=10,
    distance_measure_type="COSINE_DISTANCE",
)

# Create endpoint
endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
    display_name="hvac-manuals-endpoint",
    public_endpoint_enabled=True,
)

# Deploy index to endpoint
endpoint.deploy_index(
    index=index,
    deployed_index_id="hvac-manuals-deployed",
)
```

### Step 5: Set Up RAG Engine

```python
from vertexai.preview import rag

# Create corpus
corpus = rag.create_corpus(
    display_name="HVAC Manuals",
    description="Collection of HVAC equipment manuals and documentation",
)

print(f"Corpus created: {corpus.name}")
# Note this name for VERTEX_RAG_CORPUS env var
```

## Usage

### Using Unified RAG Interface

```python
from services.rag import UnifiedRAG, RAGProvider

# Auto-select provider based on config
rag = UnifiedRAG()

# Or force a specific provider
rag = UnifiedRAG(force_provider=RAGProvider.VERTEX)

# Query
response = await rag.query(
    query="How do I reset error code E01?",
    equipment_context={"brand": "Carrier", "model": "24ACC636"},
)

print(f"Answer: {response.answer}")
print(f"Provider: {response.provider.value}")
print(f"Confidence: {response.confidence_score}")
```

### Using Embedder with Provider Selection

```python
from services.rag import HVACEmbedder, EmbeddingProvider

embedder = HVACEmbedder()

# Automatically uses configured provider
embeddings = await embedder.embed_documents(["HVAC troubleshooting guide..."])

print(f"Provider: {embedder._active_provider.value}")
print(f"Dimension: {embedder.dimension}")
```

### Using Vector Store with Provider Selection

```python
from services.rag import HVACVectorStore, VectorStoreProvider

store = HVACVectorStore()

# Automatically uses configured provider
results = await store.search(query_embedding, top_k=10)

print(f"Provider: {store.provider.value}")
```

## Migration Guide

### From Custom to Vertex AI

1. **Set up GCP resources** (Document AI, Vector Search, RAG Engine)

2. **Update environment variables:**
   ```bash
   EMBEDDING_PROVIDER=vertex
   VECTOR_STORE_PROVIDER=vertex
   RAG_PROVIDER=vertex
   ```

3. **Re-index documents** - Vertex AI uses different embedding dimensions

4. **Test queries** - Verify responses are comparable

### From Vertex AI to Custom

1. **Ensure local services are running** (Qdrant, PostgreSQL)

2. **Update environment variables:**
   ```bash
   EMBEDDING_PROVIDER=openai
   VECTOR_STORE_PROVIDER=qdrant
   RAG_PROVIDER=custom
   ```

3. **Re-index documents** - Custom uses OpenAI embeddings (1536 dim)

## Comparison

| Feature | Custom | Vertex AI |
|---------|--------|-----------|
| **Embeddings** | OpenAI (1536 dim) | Vertex (768 dim) |
| **Vector DB** | Qdrant (self-hosted) | Vector Search (managed) |
| **LLM** | Claude | Gemini |
| **Grounding** | Custom guardrails | Built-in |
| **Cost** | Pay per API call | Pay per use |
| **Control** | Full | Limited |
| **Setup** | More complex | Simpler (managed) |
| **Scaling** | Manual | Automatic |

## Troubleshooting

### "Vertex AI not configured"

Ensure all required environment variables are set:
```bash
GCP_PROJECT_ID=...
GCP_LOCATION=...
VERTEX_RAG_CORPUS=...  # For RAG Engine
```

### "Permission denied"

Check service account permissions:
```bash
gcloud projects get-iam-policy hvac-ai-assistant
```

Required roles:
- `roles/aiplatform.user`
- `roles/documentai.apiUser`

### "Embedding dimension mismatch"

When switching providers, you must re-index all documents:
- OpenAI: 1536 dimensions
- Vertex AI: 768 dimensions

```bash
# Delete old Qdrant collection
curl -X DELETE http://localhost:6333/collections/hvac_manuals

# Re-upload all documents via admin API
```

### "RAG Engine quota exceeded"

Check your Vertex AI quotas in Cloud Console:
- Queries per minute
- Documents per corpus
- Tokens per request


