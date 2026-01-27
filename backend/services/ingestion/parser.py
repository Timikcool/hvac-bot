"""PDF and document parsing with cascading fallback chain.

Parser Chain:
1. Google Document AI (primary) - best for tables, forms, native PDF
2. Gemini Vision (fallback 1) - Google's vision model, no content filter issues
3. Claude Vision (fallback 2) - good for diagrams, schematics
4. OpenAI Vision (fallback 3) - alternative vision model
5. Local PyMuPDF (last resort) - basic text extraction

Features:
- Checkpointing: Saves each page result to disk so processing can resume after restart
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from config import get_settings
from core.llm import LLMClient, OpenAIVisionClient
from core.logging import get_logger

settings = get_settings()

logger = get_logger("ingestion.parser")


class ParserMethod(Enum):
    """Parser method used for extraction."""
    DOCUMENT_AI = "document_ai"
    GEMINI_VISION = "gemini_vision"
    CLAUDE_VISION = "claude_vision"
    OPENAI_VISION = "openai_vision"
    LOCAL_TEXT = "local_text"


@dataclass
class ParsedPage:
    """A parsed page from a document."""

    page_number: int
    text: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    diagrams: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""  # Original OCR/extracted text
    method: ParserMethod = ParserMethod.LOCAL_TEXT


@dataclass
class ParsedDocument:
    """A fully parsed document."""

    content: str
    pages: list[ParsedPage]
    images: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    metadata: dict[str, Any]
    file_hash: str
    page_count: int
    primary_method: ParserMethod = ParserMethod.LOCAL_TEXT


VISION_EXTRACTION_PROMPT = """You are extracting content from an HVAC technical manual page for a search/retrieval system.

Analyze this page image and extract ALL content in a structured format:

## INSTRUCTIONS

1. **TEXT CONTENT**: Extract all readable text, preserving structure (headers, paragraphs, lists)

2. **TABLES**: If there are tables (specifications, error codes, troubleshooting charts):
   - Extract the complete table data
   - Format as: TABLE: [Title if any]
   - Then list rows with | separators
   - Example:
     TABLE: Refrigerant Charge by Model
     | Model | R-410A Charge | 
     | 24ACC36 | 5 lbs 4 oz |
     | 24ACC48 | 7 lbs 8 oz |

3. **DIAGRAMS/SCHEMATICS**: If there are wiring diagrams, refrigerant piping, or technical drawings:
   - Describe what the diagram shows
   - List any labeled components, wire colors, terminal designations
   - Note any specifications shown (voltages, pressures, etc.)
   - Format as: DIAGRAM: [Type] - [Description]
   - Example:
     DIAGRAM: Wiring Schematic - Low voltage control circuit
     Components: R (24V), C (Common), Y (Cooling), G (Fan), W (Heat)
     Transformer: 240V primary to 24V secondary

4. **ERROR CODES**: If error/fault codes are shown:
   - Extract code, description, and troubleshooting steps
   - Format as: ERROR CODE [code]: [description] - [cause/solution]

5. **SAFETY WARNINGS**: Capture any WARNING, CAUTION, or DANGER notices verbatim

6. **SPECIFICATIONS**: Extract any specs with exact values and units

Output the complete extracted content. Be thorough - this will be used for technician search queries."""


class CascadingParser:
    """Parse documents using a cascading fallback chain.
    
    Tries parsers in order of quality:
    1. Document AI - Best for structured documents
    2. Gemini Vision - Google's vision model, no content filter issues
    3. Claude Vision - Good for technical diagrams
    4. OpenAI Vision - Fallback vision model
    5. Local text extraction - Last resort
    
    Features:
    - Checkpointing: Each page is saved to disk after processing
    - Resume: On restart, already-processed pages are loaded from cache
    """

    def __init__(self):
        self.claude_client = LLMClient()
        self.openai_client = OpenAIVisionClient()
        self._gemini_client = None
        self._gemini_available: bool | None = None
        self._document_ai_parser = None
        self._document_ai_available: bool | None = None
        
        # Setup checkpoint directory
        self.checkpoint_dir = Path(settings.data_dir) / "parse_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_checkpoint_path(self, file_hash: str, page_num: int) -> Path:
        """Get checkpoint file path for a specific page."""
        doc_dir = self.checkpoint_dir / file_hash
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir / f"page_{page_num:04d}.json"
    
    def _save_page_checkpoint(self, file_hash: str, page: "ParsedPage") -> None:
        """Save a parsed page to checkpoint."""
        checkpoint_path = self._get_checkpoint_path(file_hash, page.page_number)
        data = {
            "page_number": page.page_number,
            "text": page.text,
            "tables": page.tables,
            "diagrams": page.diagrams,
            "raw_text": page.raw_text,
            "method": page.method.value,
        }
        with open(checkpoint_path, "w") as f:
            json.dump(data, f)
    
    def _load_page_checkpoint(self, file_hash: str, page_num: int) -> "ParsedPage | None":
        """Load a parsed page from checkpoint if exists."""
        checkpoint_path = self._get_checkpoint_path(file_hash, page_num)
        if not checkpoint_path.exists():
            return None
        try:
            with open(checkpoint_path, "r") as f:
                data = json.load(f)
            return ParsedPage(
                page_number=data["page_number"],
                text=data["text"],
                tables=data.get("tables", []),
                diagrams=data.get("diagrams", []),
                raw_text=data.get("raw_text", ""),
                method=ParserMethod(data.get("method", "local_text")),
            )
        except Exception as e:
            logger.warning(f"PARSER | Failed to load checkpoint for page {page_num}: {e}")
            return None
    
    def _count_cached_pages(self, file_hash: str, total_pages: int) -> int:
        """Count how many pages are already cached."""
        cached = 0
        for page_num in range(total_pages):
            if self._get_checkpoint_path(file_hash, page_num).exists():
                cached += 1
        return cached
    
    def _clear_checkpoints(self, file_hash: str) -> None:
        """Clear checkpoints for a document (after successful ingestion)."""
        doc_dir = self.checkpoint_dir / file_hash
        if doc_dir.exists():
            import shutil
            shutil.rmtree(doc_dir)
            logger.info(f"PARSER | Cleared checkpoints for {file_hash[:12]}...")

    @property
    def gemini_client(self):
        """Lazy-load Gemini client."""
        if self._gemini_client is None:
            try:
                from core.gemini import GeminiClient
                client = GeminiClient()
                if client.is_configured:
                    self._gemini_client = client
                    self._gemini_available = True
                    logger.info("PARSER | Gemini Vision configured and available")
                else:
                    self._gemini_available = False
            except Exception as e:
                self._gemini_available = False
                logger.debug(f"PARSER | Gemini unavailable: {e}")
        return self._gemini_client

    @property
    def document_ai_parser(self):
        """Lazy-load Document AI parser."""
        if self._document_ai_parser is None:
            try:
                from services.gcp.document_ai import DocumentAIParser
                parser = DocumentAIParser()
                if parser.is_configured:
                    self._document_ai_parser = parser
                    self._document_ai_available = True
                    logger.info("PARSER | Document AI configured and available")
                else:
                    self._document_ai_available = False
                    logger.info("PARSER | Document AI not configured, will use vision fallback")
            except Exception as e:
                self._document_ai_available = False
                logger.warning(f"PARSER | Document AI unavailable: {e}")
        return self._document_ai_parser

    async def parse_pdf_async(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Parse a PDF using cascading fallback chain.

        Args:
            file_path: Path to PDF file
            metadata: Optional metadata (brand, model, etc.)

        Returns:
            ParsedDocument with extracted content
        """
        parse_start = time.time()
        
        file_path = Path(file_path)
        metadata = metadata or {}
        file_size_mb = file_path.stat().st_size / (1024 * 1024)

        # Calculate file hash
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        logger.info(f"")
        logger.info(f"PARSER | ╔══════════════════════════════════════════════════════════════")
        logger.info(f"PARSER | ║ 📚 STARTING DOCUMENT PARSE")
        logger.info(f"PARSER | ║ File: {file_path.name}")
        logger.info(f"PARSER | ║ Size: {file_size_mb:.2f} MB")
        logger.info(f"PARSER | ╚══════════════════════════════════════════════════════════════")

        # Try Document AI first (whole document)
        if self.document_ai_parser is not None:
            try:
                logger.info(f"PARSER | 🔄 Trying Document AI (primary)...")
                result = await self.document_ai_parser.parse_pdf(file_path, metadata)
                
                # Convert DocumentAIResult to ParsedDocument
                pages = [
                    ParsedPage(
                        page_number=p.page_number,
                        text=p.text,
                        tables=p.tables,
                        raw_text=p.text,
                        method=ParserMethod.DOCUMENT_AI,
                    )
                    for p in result.pages
                ]
                
                # Save all pages to checkpoint (for consistency with vision path)
                for page in pages:
                    self._save_page_checkpoint(file_hash, page)
                logger.info(f"PARSER | 💾 Saved {len(pages)} pages to checkpoint")
                
                total_time = time.time() - parse_start
                logger.info(f"PARSER | ✅ Document AI succeeded in {total_time:.1f}s")
                
                return ParsedDocument(
                    content=result.content,
                    pages=pages,
                    images=[],
                    tables=result.tables,
                    metadata={
                        **metadata,
                        "file_path": str(file_path),
                        "file_name": file_path.name,
                    },
                    file_hash=file_hash,
                    page_count=result.page_count,
                    primary_method=ParserMethod.DOCUMENT_AI,
                )
            except Exception as e:
                logger.warning(f"PARSER | ⚠️ Document AI failed: {e}, falling back to vision")

        # Fallback to page-by-page vision processing
        logger.info(f"PARSER | 🔄 Using vision-based parsing (Gemini → Claude → OpenAI → Local)")
        return await self._parse_with_vision_fallback(file_path, metadata, file_hash, parse_start)

    async def _parse_with_vision_fallback(
        self,
        file_path: Path,
        metadata: dict[str, Any],
        file_hash: str,
        parse_start: float,
    ) -> ParsedDocument:
        """Parse document using vision models with fallback chain.
        
        Features checkpointing: each page is saved after processing, 
        so the process can resume after restart.
        """

        doc = fitz.open(file_path)
        page_count = len(doc)
        
        # Check for cached pages (resume support)
        cached_count = self._count_cached_pages(file_hash, page_count)
        if cached_count > 0:
            logger.info(f"PARSER | 📖 Document opened | {page_count} pages | 💾 {cached_count} already cached (resuming)")
        else:
            logger.info(f"PARSER | 📖 Document opened | {page_count} pages")

        pages: list[ParsedPage] = [None] * page_count  # type: ignore
        all_tables = []
        all_diagrams = []

        # Track methods used
        method_counts = {
            ParserMethod.GEMINI_VISION: 0,
            ParserMethod.CLAUDE_VISION: 0,
            ParserMethod.OPENAI_VISION: 0,
            ParserMethod.LOCAL_TEXT: 0,
        }
        
        # Track cache stats
        pages_from_cache = 0
        pages_processed = 0

        # Process pages in parallel batches
        batch_size = 10
        total_batches = (page_count + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, page_count)
            batch_pages = list(range(batch_start, batch_end))
            
            # Check which pages in this batch are already cached
            cached_pages = {}
            pages_to_process = []
            for page_num in batch_pages:
                cached = self._load_page_checkpoint(file_hash, page_num)
                if cached:
                    cached_pages[page_num] = cached
                    pages[page_num] = cached
                    all_tables.extend(cached.tables)
                    all_diagrams.extend(cached.diagrams)
                    method_counts[cached.method] += 1
                    pages_from_cache += 1
                else:
                    pages_to_process.append(page_num)
            
            # Skip batch if all pages are cached
            if not pages_to_process:
                logger.info(f"PARSER | 📦 BATCH {batch_idx + 1}/{total_batches} | Pages {batch_start + 1}-{batch_end} | 💾 All cached, skipping")
                continue
            
            logger.info(f"")
            logger.info(f"PARSER | ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            if cached_pages:
                logger.info(f"PARSER | 📦 BATCH {batch_idx + 1}/{total_batches} | Pages {batch_start + 1}-{batch_end} | {len(cached_pages)} cached, {len(pages_to_process)} to process")
            else:
                logger.info(f"PARSER | 📦 BATCH {batch_idx + 1}/{total_batches} | Pages {batch_start + 1}-{batch_end} of {page_count}")
            logger.info(f"PARSER | ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            # Create tasks for parallel processing (only uncached pages)
            tasks = []
            for page_num in pages_to_process:
                page = doc[page_num]
                tasks.append(self._process_page_with_fallback(doc, page, page_num, metadata, page_count, file_hash))
            
            # Process batch in parallel
            batch_start_time = time.time()
            results = await asyncio.gather(*tasks)
            batch_duration = time.time() - batch_start_time
            
            # Collect results and save checkpoints
            batch_tables = 0
            batch_diagrams = 0
            for i, result in enumerate(results):
                page_num = pages_to_process[i]
                pages[page_num] = result
                all_tables.extend(result.tables)
                all_diagrams.extend(result.diagrams)
                batch_tables += len(result.tables)
                batch_diagrams += len(result.diagrams)
                method_counts[result.method] += 1
                pages_processed += 1
                
                # Save checkpoint for this page
                self._save_page_checkpoint(file_hash, result)
            
            logger.info(f"PARSER | ✅ Batch complete | {batch_duration:.1f}s | {batch_tables} tables, {batch_diagrams} diagrams | 💾 Saved")
            
            # Brief pause between batches to respect rate limits
            if batch_idx < total_batches - 1:
                await asyncio.sleep(0.5)

        # Combine all text
        full_content = "\n\n---PAGE BREAK---\n\n".join(p.text for p in pages)

        total_time = time.time() - parse_start
        avg_time_per_page = total_time / page_count if page_count > 0 else 0
        
        # Determine primary method
        primary_method = max(method_counts, key=method_counts.get)
        
        logger.info(f"")
        logger.info(f"PARSER | ╔══════════════════════════════════════════════════════════════")
        logger.info(f"PARSER | ║ ✅ PARSING COMPLETE")
        logger.info(f"PARSER | ║ Total time: {total_time:.1f}s ({avg_time_per_page:.1f}s per page)")
        logger.info(f"PARSER | ║ Pages: {page_count} ({pages_from_cache} from cache, {pages_processed} processed)")
        logger.info(f"PARSER | ║ Tables found: {len(all_tables)}")
        logger.info(f"PARSER | ║ Diagrams found: {len(all_diagrams)}")
        logger.info(f"PARSER | ║ Content extracted: {len(full_content):,} characters")
        logger.info(f"PARSER | ║ Methods: Gemini={method_counts[ParserMethod.GEMINI_VISION]}, Claude={method_counts[ParserMethod.CLAUDE_VISION]}, OpenAI={method_counts[ParserMethod.OPENAI_VISION]}, Local={method_counts[ParserMethod.LOCAL_TEXT]}")
        logger.info(f"PARSER | ╚══════════════════════════════════════════════════════════════")
        logger.info(f"")

        return ParsedDocument(
            content=full_content,
            pages=pages,
            images=all_diagrams,
            tables=all_tables,
            metadata={
                **metadata,
                "file_path": str(file_path),
                "file_name": file_path.name,
            },
            file_hash=file_hash,
            page_count=page_count,
            primary_method=primary_method,
        )

    async def _process_page_with_fallback(
        self,
        doc: fitz.Document,
        page: fitz.Page,
        page_num: int,
        metadata: dict[str, Any],
        total_pages: int,
        file_hash: str = "",
    ) -> ParsedPage:
        """Process a page using cascading fallback: Gemini → Claude → OpenAI → Local."""
        
        # Get raw text first (needed for all fallbacks)
        raw_text = page.get_text()
        
        # Render page to image
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("png")
        
        # Build context
        context = f"Page {page_num + 1} of {metadata.get('title', 'HVAC Document')}"
        if metadata.get("brand"):
            context += f" | Brand: {metadata['brand']}"
        if metadata.get("model"):
            context += f" | Model: {metadata['model']}"
        
        prompt = f"{VISION_EXTRACTION_PROMPT}\n\nContext: {context}"
        
        # Try Gemini Vision first (no content filter issues)
        if self._gemini_available is not False and self.gemini_client:
            try:
                start_time = time.time()
                response = await self.gemini_client.generate_with_image(
                    prompt=prompt,
                    image_bytes=image_bytes,
                    mime_type="image/png",
                    max_tokens=4000,
                )
                duration = time.time() - start_time
                extracted_text = response.content
                
                logger.info(f"PARSER |   📄 Page {page_num + 1}/{total_pages} | Gemini ✓ | {duration:.1f}s | {len(extracted_text)} chars")
                
                return self._create_parsed_page(page_num, extracted_text, raw_text, ParserMethod.GEMINI_VISION)
                
            except Exception as gemini_error:
                logger.warning(f"PARSER |   ⚠️ Page {page_num + 1}/{total_pages} | Gemini failed: {type(gemini_error).__name__}, trying Claude...")
        
        # Try Claude Vision
        try:
            start_time = time.time()
            response = await self.claude_client.generate_with_vision(
                prompt=prompt,
                image_data=image_bytes,
                image_media_type="image/png",
                max_tokens=4000,
                temperature=0,
            )
            duration = time.time() - start_time
            extracted_text = response.content
            
            tokens_in = response.usage.get('input_tokens', 0)
            tokens_out = response.usage.get('output_tokens', 0)
            logger.info(f"PARSER |   📄 Page {page_num + 1}/{total_pages} | Claude ✓ | {duration:.1f}s | {tokens_in}→{tokens_out} tokens")
            
            return self._create_parsed_page(page_num, extracted_text, raw_text, ParserMethod.CLAUDE_VISION)
            
        except Exception as claude_error:
            # Check if it's a content filter issue
            error_str = str(claude_error)
            if "content filtering" in error_str.lower() or "blocked" in error_str.lower():
                logger.warning(f"PARSER |   🛡️ Page {page_num + 1}/{total_pages} | Claude content filter, trying OpenAI...")
            else:
                logger.warning(f"PARSER |   ⚠️ Page {page_num + 1}/{total_pages} | Claude failed: {type(claude_error).__name__}, trying OpenAI...")
        
        # Try OpenAI Vision
        if self.openai_client.is_configured:
            try:
                start_time = time.time()
                response = await self.openai_client.generate_with_vision(
                    prompt=prompt,
                    image_data=image_bytes,
                    image_media_type="image/png",
                    max_tokens=4000,
                    temperature=0,
                )
                duration = time.time() - start_time
                extracted_text = response.content
                
                tokens_in = response.usage.get('input_tokens', 0)
                tokens_out = response.usage.get('output_tokens', 0)
                logger.info(f"PARSER |   📄 Page {page_num + 1}/{total_pages} | OpenAI ✓ | {duration:.1f}s | {tokens_in}→{tokens_out} tokens")
                
                return self._create_parsed_page(page_num, extracted_text, raw_text, ParserMethod.OPENAI_VISION)
                
            except Exception as openai_error:
                logger.warning(f"PARSER |   ⚠️ Page {page_num + 1}/{total_pages} | OpenAI failed: {type(openai_error).__name__}, using local extraction...")
        else:
            logger.debug(f"PARSER |   Page {page_num + 1}/{total_pages} | OpenAI not configured, using local extraction...")
        
        # Last resort: local text extraction
        logger.info(f"PARSER |   📝 Page {page_num + 1}/{total_pages} | Local extraction | {len(raw_text)} chars")
        return self._create_parsed_page(page_num, raw_text, raw_text, ParserMethod.LOCAL_TEXT)
    
    def _create_parsed_page(
        self,
        page_num: int,
        extracted_text: str,
        raw_text: str,
        method: ParserMethod,
    ) -> ParsedPage:
        """Create a ParsedPage with extracted tables and diagrams."""
        tables = self._extract_tables_from_text(extracted_text, page_num)
        diagrams = self._extract_diagrams_from_text(extracted_text, page_num)
        
        return ParsedPage(
            page_number=page_num + 1,
            text=extracted_text,
            tables=tables,
            diagrams=diagrams,
            raw_text=raw_text,
            method=method,
        )

    def _extract_tables_from_text(
        self,
        text: str,
        page_num: int,
    ) -> list[dict[str, Any]]:
        """Extract table structures from the vision-extracted text."""
        tables = []
        lines = text.split("\n")

        current_table = None
        table_lines = []

        for line in lines:
            if line.strip().startswith("TABLE:"):
                # Start new table
                if current_table and table_lines:
                    tables.append({
                        "page": page_num + 1,
                        "title": current_table,
                        "content": "\n".join(table_lines),
                    })
                current_table = line.replace("TABLE:", "").strip()
                table_lines = []
            elif current_table and "|" in line:
                table_lines.append(line.strip())
            elif current_table and line.strip() == "":
                # End of table
                if table_lines:
                    tables.append({
                        "page": page_num + 1,
                        "title": current_table,
                        "content": "\n".join(table_lines),
                    })
                current_table = None
                table_lines = []

        # Don't forget last table
        if current_table and table_lines:
                        tables.append({
                            "page": page_num + 1,
                "title": current_table,
                "content": "\n".join(table_lines),
                        })

        return tables

    def _extract_diagrams_from_text(
        self,
        text: str,
        page_num: int,
    ) -> list[dict[str, Any]]:
        """Extract diagram descriptions from the vision-extracted text."""
        diagrams = []
        lines = text.split("\n")

        current_diagram = None
        diagram_lines = []

        for line in lines:
            if line.strip().startswith("DIAGRAM:"):
                # Start new diagram description
                if current_diagram and diagram_lines:
                    diagrams.append({
                        "page": page_num + 1,
                        "type": current_diagram,
                        "description": "\n".join(diagram_lines),
                    })
                current_diagram = line.replace("DIAGRAM:", "").strip()
                diagram_lines = []
            elif current_diagram:
                if line.strip().startswith(("TABLE:", "ERROR CODE", "##")):
                    # End of diagram section
                    diagrams.append({
                        "page": page_num + 1,
                        "type": current_diagram,
                        "description": "\n".join(diagram_lines),
                    })
                    current_diagram = None
                    diagram_lines = []
                elif line.strip():
                    diagram_lines.append(line.strip())

        # Don't forget last diagram
        if current_diagram and diagram_lines:
            diagrams.append({
                "page": page_num + 1,
                "type": current_diagram,
                "description": "\n".join(diagram_lines),
            })

        return diagrams


# Aliases for backward compatibility
ManualParser = CascadingParser


class QuickParser:
    """Fast parser using only text extraction (no vision).

    Use for quick imports or when cost is a concern.
    """

    def parse_pdf(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """Parse PDF using basic text extraction only."""
        file_path = Path(file_path)
        metadata = metadata or {}

        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        doc = fitz.open(file_path)
        pages = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            pages.append(ParsedPage(
                page_number=page_num + 1,
                text=text,
                raw_text=text,
                method=ParserMethod.LOCAL_TEXT,
            ))

        full_content = "\n\n".join(p.text for p in pages)

        return ParsedDocument(
            content=full_content,
            pages=pages,
            images=[],
            tables=[],
            metadata={
                **metadata,
                "file_path": str(file_path),
                "file_name": file_path.name,
            },
            file_hash=file_hash,
            page_count=len(doc),
            primary_method=ParserMethod.LOCAL_TEXT,
        )
