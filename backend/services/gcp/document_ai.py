"""Google Document AI parser for HVAC manuals.

Provides high-quality document parsing with native support for:
- Text extraction with layout preservation
- Table detection and extraction
- Form field parsing
- No content filtering issues

Supports both online processing (≤15 pages) and batch processing (large documents).
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging import get_logger

logger = get_logger("gcp.document_ai")


@dataclass
class DocumentAIPage:
    """Parsed page from Document AI."""
    
    page_number: int
    text: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    form_fields: list[dict[str, Any]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class DocumentAIResult:
    """Result from Document AI processing."""
    
    content: str
    pages: list[DocumentAIPage]
    tables: list[dict[str, Any]]
    form_fields: list[dict[str, Any]]
    page_count: int


class DocumentAIParser:
    """Parse documents using Google Document AI.
    
    Uses the Layout Parser processor for general documents,
    or can be configured to use specialized processors.
    
    Supports:
    - Online processing: For documents ≤15 pages (synchronous, fast)
    - Batch processing: For larger documents (async via GCS)
    """
    
    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        processor_id: str | None = None,
        credentials_path: str | None = None,
        gcs_bucket: str | None = None,
    ):
        """Initialize Document AI parser.
        
        Args:
            project_id: GCP project ID
            location: Processor location (e.g., 'us' or 'eu')
            processor_id: Document AI processor ID
            credentials_path: Path to service account JSON
            gcs_bucket: GCS bucket for batch processing
        """
        from config import get_settings
        settings = get_settings()
        
        self.project_id = project_id or settings.gcp_project_id
        self.location = location or settings.gcp_location
        self.processor_id = processor_id or settings.document_ai_processor_id
        self.gcs_bucket = gcs_bucket or settings.document_ai_gcs_bucket
        self.max_online_pages = settings.document_ai_max_online_pages
        
        # Set credentials if provided
        creds_path = credentials_path or settings.gcp_credentials_path
        if creds_path and os.path.exists(creds_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        
        self._client = None
        self._storage_client = None
        self._initialized = False
    
    @property
    def is_configured(self) -> bool:
        """Check if Document AI is properly configured."""
        return bool(self.project_id and self.processor_id)
    
    @property
    def batch_enabled(self) -> bool:
        """Check if batch processing is available."""
        return bool(self.gcs_bucket)
    
    def _get_client(self):
        """Lazy-load the Document AI client."""
        if self._client is None:
            try:
                from google.cloud import documentai_v1 as documentai
                
                if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                    try:
                        import google.auth
                        credentials, project = google.auth.default()
                        logger.debug(f"DOCAI | Using ADC credentials")
                    except Exception:
                        raise ValueError(
                            "Document AI requires service account credentials. "
                            "Set GCP_CREDENTIALS_PATH to your service account JSON file, "
                            "or run 'gcloud auth application-default login'"
                        )
                
                self._client = documentai.DocumentProcessorServiceClient()
                self._initialized = True
                logger.info("DOCAI | Client initialized successfully")
            except ImportError as e:
                logger.error(f"DOCAI | Missing dependency: {e}")
                raise
            except Exception as e:
                logger.error(f"DOCAI | Failed to initialize client: {e}")
                raise
        return self._client
    
    def _get_storage_client(self):
        """Lazy-load the GCS client for batch processing."""
        if self._storage_client is None:
            try:
                from google.cloud import storage
                self._storage_client = storage.Client()
                logger.info("DOCAI | GCS client initialized")
            except Exception as e:
                logger.error(f"DOCAI | Failed to initialize GCS client: {e}")
                raise
        return self._storage_client
    
    @property
    def processor_name(self) -> str:
        """Get the full processor resource name."""
        return f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"
    
    def _get_page_count(self, file_path: Path) -> int:
        """Get page count from PDF without full processing."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            count = len(doc)
            doc.close()
            return count
        except Exception as e:
            logger.warning(f"DOCAI | Could not get page count: {e}")
            return 0  # Unknown, will try online first
    
    async def parse_pdf(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentAIResult:
        """Parse a PDF using Document AI.
        
        Automatically routes to online or batch processing based on page count.
        
        Args:
            file_path: Path to the PDF file
            metadata: Optional metadata (unused, for API compatibility)
            
        Returns:
            DocumentAIResult with extracted content
        """
        file_path = Path(file_path)
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        page_count = self._get_page_count(file_path)
        
        logger.info(f"")
        logger.info(f"DOCAI | ╔══════════════════════════════════════════════════════════════")
        logger.info(f"DOCAI | ║ 📄 DOCUMENT AI PARSING")
        logger.info(f"DOCAI | ║ File: {file_path.name}")
        logger.info(f"DOCAI | ║ Size: {file_size_mb:.2f} MB")
        logger.info(f"DOCAI | ║ Pages: {page_count}")
        
        # Route to appropriate processing method
        if page_count <= self.max_online_pages:
            logger.info(f"DOCAI | ║ Method: Online (≤{self.max_online_pages} pages)")
            logger.info(f"DOCAI | ╚══════════════════════════════════════════════════════════════")
            return await self._process_online(file_path)
        elif self.batch_enabled:
            logger.info(f"DOCAI | ║ Method: Batch Processing ({page_count} pages via GCS)")
            logger.info(f"DOCAI | ╚══════════════════════════════════════════════════════════════")
            return await self._process_batch(file_path)
        else:
            # Document too large and batch not configured
            raise ValueError(
                f"Document has {page_count} pages but batch processing is not configured. "
                f"Set DOCUMENT_AI_GCS_BUCKET to enable batch processing for large documents, "
                f"or document will fall back to vision-based parsing."
            )
    
    async def _process_online(self, file_path: Path) -> DocumentAIResult:
        """Process document using online (synchronous) API.
        
        Limited to 15 pages max.
        """
        from google.cloud import documentai_v1 as documentai
        
        start_time = time.time()
        
        with open(file_path, "rb") as f:
            content = f.read()
        
        client = self._get_client()
        
        raw_document = documentai.RawDocument(
            content=content,
            mime_type="application/pdf",
        )
        
        request = documentai.ProcessRequest(
            name=self.processor_name,
            raw_document=raw_document,
        )
        
        logger.info(f"DOCAI | 🔄 Sending to Document AI (online)...")
        
        try:
            result = client.process_document(request=request)
            document = result.document
            
            duration = time.time() - start_time
            return self._parse_document_response(document, duration)
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"DOCAI | ❌ Online processing failed ({duration:.1f}s): {e}")
            raise
    
    async def _process_batch(self, file_path: Path) -> DocumentAIResult:
        """Process document using batch (async) API via GCS.
        
        For documents larger than 15 pages.
        """
        from google.cloud import documentai_v1 as documentai
        
        start_time = time.time()
        job_id = str(uuid.uuid4())[:8]
        
        # Upload to GCS
        gcs_input_uri = await self._upload_to_gcs(file_path, job_id)
        gcs_output_uri = f"gs://{self.gcs_bucket}/docai-output/{job_id}/"
        
        logger.info(f"DOCAI | 🔄 Starting batch processing...")
        logger.info(f"DOCAI |   Input: {gcs_input_uri}")
        logger.info(f"DOCAI |   Output: {gcs_output_uri}")
        
        client = self._get_client()
        
        # Create batch request
        gcs_document = documentai.GcsDocument(
            gcs_uri=gcs_input_uri,
            mime_type="application/pdf",
        )
        
        gcs_documents = documentai.GcsDocuments(documents=[gcs_document])
        
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=gcs_documents,
        )
        
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                gcs_uri=gcs_output_uri,
            ),
        )
        
        request = documentai.BatchProcessRequest(
            name=self.processor_name,
            input_documents=input_config,
            document_output_config=output_config,
        )
        
        try:
            # Start batch operation
            operation = client.batch_process_documents(request=request)
            logger.info(f"DOCAI | 📋 Batch operation started: {operation.operation.name}")
            
            # Poll for completion
            result = await self._wait_for_operation(operation)
            
            # Download and parse results
            document = await self._download_batch_result(gcs_output_uri)
            
            duration = time.time() - start_time
            parsed_result = self._parse_document_response(document, duration)
            
            # Cleanup GCS files
            await self._cleanup_gcs(gcs_input_uri, gcs_output_uri)
            
            return parsed_result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"DOCAI | ❌ Batch processing failed ({duration:.1f}s): {e}")
            # Try to cleanup on error
            try:
                await self._cleanup_gcs(gcs_input_uri, gcs_output_uri)
            except Exception:
                pass
            raise
    
    async def _upload_to_gcs(self, file_path: Path, job_id: str) -> str:
        """Upload file to GCS for batch processing."""
        storage_client = self._get_storage_client()
        bucket = storage_client.bucket(self.gcs_bucket)
        
        blob_name = f"docai-input/{job_id}/{file_path.name}"
        blob = bucket.blob(blob_name)
        
        # Run upload in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            blob.upload_from_filename,
            str(file_path),
        )
        
        gcs_uri = f"gs://{self.gcs_bucket}/{blob_name}"
        logger.info(f"DOCAI | ✅ Uploaded to {gcs_uri}")
        return gcs_uri
    
    async def _wait_for_operation(self, operation, poll_interval: int = 5, timeout: int = 600):
        """Wait for batch operation to complete."""
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > timeout:
                raise TimeoutError(f"Batch processing timed out after {timeout}s")
            
            if operation.done():
                if operation.exception():
                    raise operation.exception()
                logger.info(f"DOCAI | ✅ Batch processing complete ({elapsed:.1f}s)")
                return operation.result()
            
            logger.debug(f"DOCAI | ⏳ Waiting for batch processing... ({elapsed:.0f}s)")
            await asyncio.sleep(poll_interval)
            
            # Refresh operation status
            operation = operation.operation
    
    async def _download_batch_result(self, gcs_output_uri: str):
        """Download and parse batch processing results from GCS."""
        from google.cloud import documentai_v1 as documentai
        import json
        
        storage_client = self._get_storage_client()
        
        # Parse bucket and prefix from URI
        uri_parts = gcs_output_uri.replace("gs://", "").split("/", 1)
        bucket_name = uri_parts[0]
        prefix = uri_parts[1] if len(uri_parts) > 1 else ""
        
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        # Find the output JSON file
        output_blob = None
        for blob in blobs:
            if blob.name.endswith(".json"):
                output_blob = blob
                break
        
        if not output_blob:
            raise ValueError(f"No output JSON found in {gcs_output_uri}")
        
        # Download and parse
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(None, output_blob.download_as_string)
        
        # Parse as Document AI document
        document_dict = json.loads(content)
        document = documentai.Document.from_json(json.dumps(document_dict))
        
        logger.info(f"DOCAI | ✅ Downloaded results from {output_blob.name}")
        return document
    
    async def _cleanup_gcs(self, input_uri: str, output_uri: str):
        """Clean up temporary GCS files."""
        storage_client = self._get_storage_client()
        
        for uri in [input_uri, output_uri]:
            try:
                uri_parts = uri.replace("gs://", "").split("/", 1)
                bucket_name = uri_parts[0]
                prefix = uri_parts[1] if len(uri_parts) > 1 else ""
                
                bucket = storage_client.bucket(bucket_name)
                
                if uri.endswith("/"):
                    # Directory - delete all blobs with prefix
                    blobs = list(bucket.list_blobs(prefix=prefix))
                    for blob in blobs:
                        blob.delete()
                else:
                    # Single file
                    blob = bucket.blob(prefix)
                    if blob.exists():
                        blob.delete()
                        
            except Exception as e:
                logger.warning(f"DOCAI | Failed to cleanup {uri}: {e}")
        
        logger.debug(f"DOCAI | Cleaned up GCS files")
    
    def _parse_document_response(self, document, duration: float) -> DocumentAIResult:
        """Parse Document AI response into our result format."""
        pages = []
        all_tables = []
        all_form_fields = []
        
        for page_idx, page in enumerate(document.pages):
            page_text = self._get_page_text(document, page)
            tables = self._extract_tables(document, page, page_idx)
            form_fields = self._extract_form_fields(document, page)
            
            pages.append(DocumentAIPage(
                page_number=page_idx + 1,
                text=page_text,
                tables=tables,
                form_fields=form_fields,
            ))
            
            all_tables.extend(tables)
            all_form_fields.extend(form_fields)
        
        logger.info(f"")
        logger.info(f"DOCAI | ╔══════════════════════════════════════════════════════════════")
        logger.info(f"DOCAI | ║ ✅ PARSING COMPLETE")
        logger.info(f"DOCAI | ║ Time: {duration:.1f}s")
        logger.info(f"DOCAI | ║ Pages: {len(pages)}")
        logger.info(f"DOCAI | ║ Tables: {len(all_tables)}")
        logger.info(f"DOCAI | ║ Form fields: {len(all_form_fields)}")
        logger.info(f"DOCAI | ║ Content: {len(document.text):,} chars")
        logger.info(f"DOCAI | ╚══════════════════════════════════════════════════════════════")
        
        return DocumentAIResult(
            content=document.text,
            pages=pages,
            tables=all_tables,
            form_fields=all_form_fields,
            page_count=len(pages),
        )
    
    def _get_page_text(self, document, page) -> str:
        """Extract text for a specific page."""
        page_text_parts = []
        
        for paragraph in page.paragraphs:
            para_text = self._get_text_from_layout(document, paragraph.layout)
            if para_text.strip():
                page_text_parts.append(para_text)
        
        return "\n\n".join(page_text_parts)
    
    def _get_text_from_layout(self, document, layout) -> str:
        """Extract text using layout text anchor."""
        text = ""
        if layout.text_anchor and layout.text_anchor.text_segments:
            for segment in layout.text_anchor.text_segments:
                start_index = int(segment.start_index) if segment.start_index else 0
                end_index = int(segment.end_index) if segment.end_index else 0
                text += document.text[start_index:end_index]
        return text
    
    def _extract_tables(
        self,
        document,
        page,
        page_idx: int,
    ) -> list[dict[str, Any]]:
        """Extract tables from a page."""
        tables = []
        
        for table_idx, table in enumerate(page.tables):
            rows = []
            
            for row in table.header_rows:
                cells = []
                for cell in row.cells:
                    cell_text = self._get_text_from_layout(document, cell.layout)
                    cells.append(cell_text.strip())
                rows.append(cells)
            
            for row in table.body_rows:
                cells = []
                for cell in row.cells:
                    cell_text = self._get_text_from_layout(document, cell.layout)
                    cells.append(cell_text.strip())
                rows.append(cells)
            
            if rows:
                content_lines = [" | ".join(row) for row in rows]
                
                tables.append({
                    "page": page_idx + 1,
                    "table_index": table_idx,
                    "rows": rows,
                    "content": "\n".join(content_lines),
                })
        
        return tables
    
    def _extract_form_fields(
        self,
        document,
        page,
    ) -> list[dict[str, Any]]:
        """Extract form fields (key-value pairs) from a page."""
        form_fields = []
        
        for field in page.form_fields:
            field_name = self._get_text_from_layout(document, field.field_name)
            field_value = self._get_text_from_layout(document, field.field_value)
            
            if field_name.strip() or field_value.strip():
                form_fields.append({
                    "name": field_name.strip(),
                    "value": field_value.strip(),
                })
        
        return form_fields
