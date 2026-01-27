# Document Parsing

The HVAC AI Assistant uses a **cascading parser** to extract content from PDF documents (manuals, books, articles). This ensures maximum reliability and quality by trying multiple parsing methods in order of preference.

## Parser Chain

```
┌─────────────────────────────────────────────────────────────────┐
│                     CASCADING PARSER CHAIN                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. GOOGLE DOCUMENT AI (Primary)                                │
│     ├── Online processing (≤15 pages, sync)                     │
│     ├── Batch processing (>15 pages, async via GCS)             │
│     ├── Native PDF support                                      │
│     ├── Built-in table extraction                               │
│     ├── Form field detection                                    │
│     └── No content filter issues                                │
│                                                                 │
│         ↓ fails or not configured                               │
│                                                                 │
│  2. CLAUDE VISION (Fallback 1)                                  │
│     ├── Page-by-page processing                                 │
│     ├── Excellent for technical diagrams                        │
│     ├── Parallel batch processing (10 pages)                    │
│     └── May trigger content filters on some pages               │
│                                                                 │
│         ↓ fails or content filtered                             │
│                                                                 │
│  3. OPENAI VISION (Fallback 2)                                  │
│     ├── GPT-4o model                                            │
│     ├── Different content filtering policy                      │
│     └── Good alternative for filtered pages                     │
│                                                                 │
│         ↓ fails                                                 │
│                                                                 │
│  4. LOCAL TEXT EXTRACTION (Last Resort)                         │
│     ├── PyMuPDF text layer extraction                           │
│     ├── Always succeeds (if PDF has text)                       │
│     └── No table/diagram understanding                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Parser Comparison

| Feature | Document AI | Claude Vision | OpenAI Vision | Local Text |
|---------|-------------|---------------|---------------|------------|
| **Quality** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| **Tables** | Native | Via prompt | Via prompt | None |
| **Diagrams** | Detected | Described | Described | None |
| **Forms** | Native | Via prompt | Via prompt | None |
| **PDF Native** | Yes | No (render) | No (render) | Yes |
| **Content Filter** | None | Yes | Yes (different) | None |
| **Cost** | ~$1.50/1000 pages | Per token | Per token | Free |
| **Speed** | Fast | Medium | Medium | Fast |

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# ═══════════════════════════════════════════════════════════════
# DOCUMENT PARSING CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# --- Google Cloud (Optional - for Document AI) ---
# Leave empty to skip Document AI and use vision fallback chain
GCP_PROJECT_ID=your-gcp-project-id
GCP_LOCATION=us  # or us-central1, eu, etc.
GCP_CREDENTIALS_PATH=/path/to/service-account.json
DOCUMENT_AI_PROCESSOR_ID=your-processor-id

# --- Batch Processing (for documents >15 pages) ---
DOCUMENT_AI_GCS_BUCKET=your-bucket-name  # GCS bucket for large docs
DOCUMENT_AI_MAX_ONLINE_PAGES=15  # Threshold for batch processing

# --- Anthropic Claude (Required) ---
ANTHROPIC_API_KEY=your-anthropic-key
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# --- OpenAI (Required for embeddings, optional for vision fallback) ---
OPENAI_API_KEY=your-openai-key
OPENAI_VISION_MODEL=gpt-4o  # Used as vision fallback
```

### Setting Up Document AI (Optional but Recommended)

1. **Create GCP Project**
   ```bash
   gcloud projects create hvac-assistant --name="HVAC Assistant"
   gcloud config set project hvac-assistant
   ```

2. **Enable Billing**
   - Go to [GCP Console](https://console.cloud.google.com/billing)
   - Link a billing account to your project

3. **Enable Document AI API**
   ```bash
   gcloud services enable documentai.googleapis.com
   ```

4. **Create a Processor**
   ```bash
   # Create a Layout Parser processor (best for general documents)
   gcloud documentai processors create \
     --location=us \
     --type=LAYOUT_PARSER_PROCESSOR \
     --display-name="HVAC Manual Parser"
   ```
   
   Or via [Document AI Console](https://console.cloud.google.com/ai/document-ai):
   - Click "Create Processor"
   - Choose "Layout Parser" for general documents
   - Note the processor ID

5. **Create Service Account**
   ```bash
   # Create service account
   gcloud iam service-accounts create hvac-parser \
     --display-name="HVAC Parser Service Account"

   # Grant permissions
   gcloud projects add-iam-policy-binding hvac-assistant \
     --member="serviceAccount:hvac-parser@hvac-assistant.iam.gserviceaccount.com" \
     --role="roles/documentai.user"

   # Create and download key
   gcloud iam service-accounts keys create ./service-account.json \
     --iam-account=hvac-parser@hvac-assistant.iam.gserviceaccount.com
   ```

6. **Update .env**
   ```bash
   GCP_PROJECT_ID=hvac-assistant
   GCP_LOCATION=us
   GCP_CREDENTIALS_PATH=./service-account.json
   DOCUMENT_AI_PROCESSOR_ID=<processor-id-from-step-4>
   ```

### Setting Up Batch Processing (For Large Documents)

Document AI online processing has a **15-page limit**. For larger documents (like HVAC manuals with 100+ pages), batch processing via Google Cloud Storage is required.

1. **Create a GCS Bucket**
   ```bash
   # Create bucket (name must be globally unique)
   gsutil mb -l us gs://hvac-assistant-docai-temp
   
   # Set lifecycle policy to auto-delete temp files after 1 day
   cat > lifecycle.json << EOF
   {
     "rule": [
       {"action": {"type": "Delete"}, "condition": {"age": 1}}
     ]
   }
   EOF
   gsutil lifecycle set lifecycle.json gs://hvac-assistant-docai-temp
   ```

2. **Grant Service Account Access**
   ```bash
   gsutil iam ch \
     serviceAccount:hvac-parser@hvac-assistant.iam.gserviceaccount.com:objectAdmin \
     gs://hvac-assistant-docai-temp
   ```

3. **Update .env**
   ```bash
   DOCUMENT_AI_GCS_BUCKET=hvac-assistant-docai-temp
   ```

4. **How It Works**
   - Documents ≤15 pages: Processed synchronously (fast, ~1-2s/page)
   - Documents >15 pages: Uploaded to GCS, processed asynchronously, results downloaded
   - Temp files are automatically cleaned up after processing

## Usage

### Automatic (Recommended)

The parser is automatically used when uploading documents via the admin API:

```bash
curl -X POST http://localhost:8000/api/admin/documents/upload \
  -F "file=@manual.pdf" \
  -F "title=Carrier 24ACC Installation Manual" \
  -F "document_type=manual" \
  -F "brand=Carrier" \
  -F "model=24ACC36" \
  -F "use_vision=true"
```

### Programmatic

```python
from services.ingestion.parser import CascadingParser

parser = CascadingParser()

# Parse a document (uses full fallback chain)
result = await parser.parse_pdf_async(
    file_path="path/to/manual.pdf",
    metadata={
        "title": "Installation Manual",
        "brand": "Carrier",
        "model": "24ACC36",
    }
)

print(f"Parsed {result.page_count} pages")
print(f"Found {len(result.tables)} tables")
print(f"Primary method: {result.primary_method}")
```

### Quick Parse (No Vision)

For fast imports without AI processing:

```python
from services.ingestion.parser import QuickParser

parser = QuickParser()
result = parser.parse_pdf("path/to/manual.pdf")
```

## Log Output

The parser provides detailed logging:

```
PARSER | ╔══════════════════════════════════════════════════════════════
PARSER | ║ 📚 STARTING DOCUMENT PARSE
PARSER | ║ File: carrier_24acc_installation.pdf
PARSER | ║ Size: 4.25 MB
PARSER | ╚══════════════════════════════════════════════════════════════

PARSER | 🔄 Trying Document AI (primary)...
PARSER | ✅ Document AI succeeded in 12.3s

# OR if Document AI fails/not configured:

PARSER | 🔄 Using vision-based parsing (Claude → OpenAI → Local)
PARSER | 📖 Document opened | 50 pages

PARSER | ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARSER | 📦 BATCH 1/5 | Pages 1-10 of 50
PARSER | ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARSER |   📄 Page 1/50 | Claude ✓ | 8.2s | 1600→450 tokens
PARSER |   📄 Page 2/50 | Claude ✓ | 7.1s | 1400→380 tokens
PARSER |   🛡️ Page 3/50 | Claude content filter, trying OpenAI...
PARSER |   📄 Page 3/50 | OpenAI ✓ | 9.3s | 1500→420 tokens
PARSER |   📝 Page 4/50 | Local extraction | 2847 chars
...

PARSER | ╔══════════════════════════════════════════════════════════════
PARSER | ║ ✅ PARSING COMPLETE
PARSER | ║ Total time: 89.2s (1.8s per page)
PARSER | ║ Pages: 50
PARSER | ║ Tables found: 12
PARSER | ║ Diagrams found: 8
PARSER | ║ Content extracted: 125,432 characters
PARSER | ║ Methods: Claude=42, OpenAI=6, Local=2
PARSER | ╚══════════════════════════════════════════════════════════════
```

## Troubleshooting

### Document AI Not Working

1. **Check configuration**
   ```python
   from services.gcp.document_ai import DocumentAIParser
   parser = DocumentAIParser()
   print(f"Configured: {parser.is_configured}")
   ```

2. **Verify credentials**
   ```bash
   gcloud auth application-default login
   # or
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```

3. **Check API is enabled**
   ```bash
   gcloud services list --enabled | grep documentai
   ```

### Content Filter Issues

If Claude Vision blocks pages:
- The parser automatically falls back to OpenAI Vision
- If OpenAI also blocks, local text extraction is used
- Check logs for `🛡️ Content filter` messages

### Slow Processing

1. **Increase batch size** (if rate limits allow):
   ```python
   # In parser.py, adjust batch_size
   batch_size = 15  # Default is 10
   ```

2. **Use QuickParser** for non-critical documents:
   ```python
   from services.ingestion.parser import QuickParser
   parser = QuickParser()
   ```

3. **Enable Document AI** - it processes the entire document at once

## API Reference

### CascadingParser

```python
class CascadingParser:
    """Parse documents using cascading fallback chain."""
    
    async def parse_pdf_async(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Parse a PDF using cascading fallback chain."""
```

### ParsedDocument

```python
@dataclass
class ParsedDocument:
    content: str                    # Full extracted text
    pages: list[ParsedPage]         # Per-page content
    images: list[dict]              # Extracted diagrams
    tables: list[dict]              # Extracted tables
    metadata: dict[str, Any]        # Document metadata
    file_hash: str                  # SHA-256 hash
    page_count: int                 # Number of pages
    primary_method: ParserMethod    # Most used parser
```

### ParserMethod

```python
class ParserMethod(Enum):
    DOCUMENT_AI = "document_ai"     # Google Document AI
    CLAUDE_VISION = "claude_vision" # Anthropic Claude
    OPENAI_VISION = "openai_vision" # OpenAI GPT-4o
    LOCAL_TEXT = "local_text"       # PyMuPDF extraction
```

