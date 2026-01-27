"""Admin API routes for analytics, fine-tuning, and management."""

import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_analytics, get_db, get_gap_tracker, get_redis
from config import get_settings
from core.logging import get_logger
from models.conversation import Message
from services.analytics.knowledge_gaps import KnowledgeGapTracker
from services.analytics.rag_analytics import RAGAnalytics
from services.ingestion import HVACChunker
from services.rag.embedder import HVACEmbedder
from services.rag.vector_store import HVACVectorStore

logger = get_logger("api.admin")
settings = get_settings()


# ============================================================================
# EMBEDDING CHECKPOINT HELPERS
# ============================================================================

def _get_embedding_checkpoint_dir() -> Path:
    """Get the directory for embedding checkpoints."""
    checkpoint_dir = Path(settings.data_dir) / "embedding_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir


def _save_embedding_checkpoint(
    file_hash: str,
    embeddings: list[list[float]],
    chunks_data: list[dict],
    metadata: dict,
) -> None:
    """Save embeddings and chunk data to checkpoint for resuming after failures."""
    checkpoint_dir = _get_embedding_checkpoint_dir()
    checkpoint_path = checkpoint_dir / f"{file_hash}.json"
    
    data = {
        "file_hash": file_hash,
        "embeddings": embeddings,
        "chunks": chunks_data,
        "metadata": metadata,
        "created_at": datetime.now().isoformat(),
    }
    
    with open(checkpoint_path, "w") as f:
        json.dump(data, f)
    
    logger.info(f"CHECKPOINT | 💾 Saved embeddings checkpoint | {len(embeddings)} vectors | {checkpoint_path.name}")


def _load_embedding_checkpoint(file_hash: str) -> dict | None:
    """Load embeddings from checkpoint if exists."""
    checkpoint_dir = _get_embedding_checkpoint_dir()
    checkpoint_path = checkpoint_dir / f"{file_hash}.json"
    
    if not checkpoint_path.exists():
        return None
    
    try:
        with open(checkpoint_path, "r") as f:
            data = json.load(f)
        logger.info(f"CHECKPOINT | 📂 Loaded embeddings from cache | {len(data['embeddings'])} vectors")
        return data
    except Exception as e:
        logger.warning(f"CHECKPOINT | Failed to load embeddings checkpoint: {e}")
        return None


def _clear_embedding_checkpoint(file_hash: str) -> None:
    """Clear embedding checkpoint after successful ingestion."""
    checkpoint_dir = _get_embedding_checkpoint_dir()
    checkpoint_path = checkpoint_dir / f"{file_hash}.json"
    
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.info(f"CHECKPOINT | 🗑️ Cleared embeddings checkpoint | {file_hash[:12]}...")

router = APIRouter(prefix="/admin", tags=["admin"])


# Request/Response Models
class AnnotationRequest(BaseModel):
    """Message annotation request."""

    is_good_example: bool
    notes: str | None = None


class GapResolutionRequest(BaseModel):
    """Knowledge gap resolution request."""

    resolution_notes: str


class DocumentUploadResponse(BaseModel):
    """Response from document upload."""

    document_id: str
    title: str
    document_type: str
    brand: str | None = None
    model: str | None = None
    chunks_created: int
    pages_processed: int
    tables_found: int = 0
    diagrams_found: int = 0


# Document Upload Routes
@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str = Form("manual"),  # manual, book, article, reference
    brand: str | None = Form(None),
    model: str | None = Form(None),
    system_type: str | None = Form(None),
    category: str | None = Form(None),  # For books/articles: refrigeration, electrical, controls, etc.
    use_vision: bool = Form(True),
) -> DocumentUploadResponse:
    """Upload and process an HVAC document (manual, book, or article).

    Document types:
    - manual: Equipment-specific service/installation manuals
    - book: HVAC textbooks, training materials
    - article: Technical articles, white papers
    - reference: Code books, standards (EPA, ASHRAE)

    The document will be:
    1. Parsed to extract text, tables, and diagrams (using Claude Vision if enabled)
    2. Chunked into semantic sections
    3. Embedded using OpenAI
    4. Stored in the vector database for RAG retrieval
    """
    import time
    upload_start = time.time()
    
    logger.info(f"")
    logger.info(f"UPLOAD | ╔══════════════════════════════════════════════════════════════")
    logger.info(f"UPLOAD | ║ 📤 NEW DOCUMENT UPLOAD")
    logger.info(f"UPLOAD | ║ Title: {title}")
    logger.info(f"UPLOAD | ║ Type: {document_type}")
    if brand:
        logger.info(f"UPLOAD | ║ Brand: {brand}")
    if model:
        logger.info(f"UPLOAD | ║ Model: {model}")
    logger.info(f"UPLOAD | ║ Vision: {'🤖 Enabled (Claude Vision)' if use_vision else '⚡ Disabled (fast text only)'}")
    logger.info(f"UPLOAD | ╚══════════════════════════════════════════════════════════════")
    logger.info(f"")

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Validate document type
    valid_doc_types = ["manual", "book", "article", "reference"]
    if document_type not in valid_doc_types:
        raise HTTPException(status_code=400, detail=f"Invalid document_type. Must be one of: {valid_doc_types}")

    settings = get_settings()
    document_id = str(uuid4())

    # Save file temporarily
    temp_path = Path(settings.data_dir) / "temp" / f"{document_id}.pdf"
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Save uploaded file
        logger.info(f"UPLOAD | 📁 Saving file to disk...")
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        file_size_mb = temp_path.stat().st_size / (1024 * 1024)
        logger.info(f"UPLOAD | ✅ File saved | {file_size_mb:.2f} MB | {temp_path}")

        # Parse PDF
        metadata_dict = {
            "document_id": document_id,
            "document_type": document_type,
            "title": title,
            "brand": brand,
            "model": model,
            "system_type": system_type,
            "category": category,
        }

        logger.info(f"")
        logger.info(f"UPLOAD | 📖 STEP 1/4: Parsing document...")
        
        if use_vision:
            # Use Claude Vision for thorough extraction (tables, diagrams, schematics)
            logger.info(f"UPLOAD |   Using Claude Vision - this may take several minutes for large documents")
            logger.info(f"UPLOAD |   Each page will be analyzed for text, tables, diagrams, and schematics")
            from services.ingestion.parser import ManualParser
            parser = ManualParser()
            parsed = await parser.parse_pdf_async(
                file_path=temp_path,
                metadata=metadata_dict,
            )
        else:
            # Quick text-only extraction
            logger.info(f"UPLOAD |   Using fast text extraction (no diagrams/tables)")
            from services.ingestion.parser import QuickParser
            parser = QuickParser()
            parsed = parser.parse_pdf(
                file_path=temp_path,
                metadata=metadata_dict,
            )

        logger.info(
            f"UPLOAD | ✅ Parsing complete | {parsed.page_count} pages | "
            f"{len(parsed.tables)} tables | {len(parsed.images)} diagrams"
        )

        # Get file hash for checkpoint lookup
        file_hash = parsed.file_hash if hasattr(parsed, 'file_hash') else None
        
        # Check for cached embeddings (resume after Qdrant failure)
        cached_embeddings = _load_embedding_checkpoint(file_hash) if file_hash else None
        
        if cached_embeddings:
            # Resume from cached embeddings - skip chunking and embedding
            logger.info(f"")
            logger.info(f"UPLOAD | 💾 RESUMING from cached embeddings...")
            logger.info(f"UPLOAD | ⏭️ Skipping STEP 2/4 (Chunking) - loaded from cache")
            logger.info(f"UPLOAD | ⏭️ Skipping STEP 3/4 (Embeddings) - loaded from cache")
            
            embeddings = cached_embeddings["embeddings"]
            chunks_data = cached_embeddings["chunks"]
            
            # Reconstruct chunks for metadata
            from dataclasses import dataclass
            from services.ingestion.chunker import ChunkType
            
            @dataclass
            class CachedChunk:
                content: str
                chunk_type: ChunkType
                parent_section: str
                page_numbers: list
                keywords: list
            
            chunks = [
                CachedChunk(
                    content=c["content"],
                    chunk_type=ChunkType(c["chunk_type"]),
                    parent_section=c.get("parent_section", ""),
                    page_numbers=c.get("page_numbers", []),
                    keywords=c.get("keywords", []),
                )
                for c in chunks_data
            ]
            
            class EmbeddingResult:
                def __init__(self, embeddings):
                    self.embeddings = embeddings
            
            embedding_result = EmbeddingResult(embeddings)
            logger.info(f"UPLOAD | ✅ Loaded {len(embeddings)} embeddings from cache")
            
        else:
            # Normal flow: chunk and embed
            
            # Chunk document
            logger.info(f"")
            logger.info(f"UPLOAD | 📑 STEP 2/4: Chunking document...")
            
            chunker = HVACChunker()
            chunks = chunker.chunk_document(
                content=parsed.content,
                metadata={
                    "document_id": document_id,
                    "document_type": document_type,
                    "title": title,
                    "brand": brand,
                    "model": model,
                    "system_type": system_type,
                    "category": category,
                },
            )
            logger.info(f"UPLOAD | ✅ Created {len(chunks)} semantic chunks from {len(parsed.content):,} characters")

            if not chunks:
                raise HTTPException(status_code=400, detail="No content could be extracted from the PDF")

            # Embed chunks
            logger.info(f"")
            logger.info(f"UPLOAD | 🧠 STEP 3/4: Creating embeddings with OpenAI...")
            
            embedder = HVACEmbedder()
            texts_to_embed = [
                embedder.prepare_chunk_for_embedding(
                    content=chunk.content,
                    metadata={
                        "brand": brand,
                        "model": model,
                        "system_type": system_type,
                        "parent_section": chunk.parent_section,
                        "chunk_type": chunk.chunk_type.value,
                    },
                )
                for chunk in chunks
            ]

            logger.info(f"UPLOAD |   Sending {len(texts_to_embed)} chunks to OpenAI for embedding...")
            embedding_start = time.time()
            embedding_result = await embedder.embed_documents(texts_to_embed)
            embedding_time = time.time() - embedding_start
            
            # Save embedding checkpoint immediately after successful embedding
            if file_hash:
                chunks_data = [
                    {
                        "content": c.content,
                        "chunk_type": c.chunk_type.value,
                        "parent_section": c.parent_section,
                        "page_numbers": c.page_numbers,
                        "keywords": c.keywords,
                    }
                    for c in chunks
                ]
                _save_embedding_checkpoint(
                    file_hash=file_hash,
                    embeddings=embedding_result.embeddings,
                    chunks_data=chunks_data,
                    metadata={
                        "document_id": document_id,
                        "document_type": document_type,
                        "title": title,
                        "brand": brand,
                        "model": model,
                        "system_type": system_type,
                        "category": category,
                    },
                )
        logger.info(f"UPLOAD | ✅ Embeddings created | {len(embedding_result.embeddings)} vectors | {embedding_time:.1f}s")

        # Store in vector database
        logger.info(f"")
        logger.info(f"UPLOAD | 💾 STEP 4/4: Storing in Qdrant vector database...")
        
        vector_store = HVACVectorStore()

        chunk_ids = await vector_store.upsert(
            embeddings=embedding_result.embeddings,
            contents=[c.content for c in chunks],
            metadatas=[
                {
                    "document_id": document_id,
                    "document_type": document_type,
                    "title": title,
                    "brand": brand,
                    "model": model,
                    "system_type": system_type,
                    "category": category,
                    "chunk_type": c.chunk_type.value,
                    "parent_section": c.parent_section,
                    "page_numbers": c.page_numbers,
                    "keywords": c.keywords,
                }
                for c in chunks
            ],
        )
        logger.info(f"UPLOAD | ✅ Stored {len(chunk_ids)} chunks in Qdrant")

        # Clear all checkpoints after successful ingestion
        if file_hash:
            # Clear parser page checkpoints
            if 'parser' in dir() and hasattr(parser, '_clear_checkpoints'):
                parser._clear_checkpoints(file_hash)
            # Clear embedding checkpoints
            _clear_embedding_checkpoint(file_hash)

        # Move file to permanent storage
        permanent_path = Path(settings.manual_storage_path) / f"{document_id}.pdf"
        permanent_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(temp_path, permanent_path)

        total_time = time.time() - upload_start
        
        logger.info(f"")
        logger.info(f"UPLOAD | ╔══════════════════════════════════════════════════════════════")
        logger.info(f"UPLOAD | ║ ✅ UPLOAD COMPLETE!")
        logger.info(f"UPLOAD | ║ Document ID: {document_id}")
        logger.info(f"UPLOAD | ║ Title: {title}")
        logger.info(f"UPLOAD | ║ Type: {document_type}")
        logger.info(f"UPLOAD | ║ Pages: {parsed.page_count}")
        logger.info(f"UPLOAD | ║ Chunks: {len(chunks)}")
        logger.info(f"UPLOAD | ║ Tables: {len(parsed.tables)}")
        logger.info(f"UPLOAD | ║ Diagrams: {len(parsed.images)}")
        logger.info(f"UPLOAD | ║ Total time: {total_time:.1f}s")
        logger.info(f"UPLOAD | ╚══════════════════════════════════════════════════════════════")
        logger.info(f"")

        return DocumentUploadResponse(
            document_id=document_id,
            title=title,
            document_type=document_type,
            brand=brand,
            model=model,
            chunks_created=len(chunks),
            pages_processed=parsed.page_count,
            tables_found=len(parsed.tables),
            diagrams_found=len(parsed.images),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"UPLOAD | Error: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process manual: {str(e)}")
    finally:
        # Cleanup temp file if it exists
        if temp_path.exists():
            temp_path.unlink()


@router.get("/manuals")
async def list_manuals() -> dict[str, Any]:
    """List all uploaded manuals/documents with stats."""
    try:
        vector_store = HVACVectorStore()
        stats = await vector_store.get_stats()
        documents = await vector_store.list_documents()
        
        return {
            "total_chunks": stats.get("vectors_count", 0),
            "total_documents": len(documents),
            "status": stats.get("status", "unknown"),
            "documents": documents,
        }
    except Exception as e:
        logger.error(f"Error listing manuals: {e}")
        return {"total_chunks": 0, "total_documents": 0, "status": "error", "error": str(e), "documents": []}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str) -> dict[str, Any]:
    """Delete a document and all its chunks from the vector store."""
    logger.info(f"DELETE | Removing document {document_id}")

    try:
        vector_store = HVACVectorStore()
        result = await vector_store.delete_by_document(document_id)

        # Also delete the PDF file
        settings = get_settings()
        pdf_path = Path(settings.manual_storage_path) / f"{document_id}.pdf"
        if pdf_path.exists():
            pdf_path.unlink()

        return {"status": "deleted", "document_id": document_id}
    except Exception as e:
        logger.error(f"DELETE | Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Backward compatibility alias
@router.post("/manuals/upload", response_model=DocumentUploadResponse, include_in_schema=False)
async def upload_manual_compat(
    file: UploadFile = File(...),
    title: str = Form(...),
    brand: str | None = Form(None),
    model: str | None = Form(None),
    system_type: str | None = Form(None),
    use_vision: bool = Form(True),
) -> DocumentUploadResponse:
    """Backward compatible manual upload endpoint."""
    return await upload_document(
        file=file,
        title=title,
        document_type="manual",
        brand=brand,
        model=model,
        system_type=system_type,
        category=None,
        use_vision=use_vision,
    )


# Analytics Routes
@router.get("/analytics/quality-report")
async def get_quality_report(
    days: int = Query(7, ge=1, le=90),
    equipment_brand: str | None = None,
    analytics: RAGAnalytics = Depends(get_analytics),
) -> dict[str, Any]:
    """Get RAG quality report for specified period."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    report = await analytics.generate_quality_report(
        start_date=start_date,
        end_date=end_date,
        equipment_brand=equipment_brand,
    )

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "total_queries": report.total_queries,
        "avg_retrieval_score": round(report.avg_top_retrieval_score, 3),
        "avg_confidence": round(report.avg_response_confidence, 3),
        "low_confidence_rate": round(report.low_confidence_rate, 3),
        "escalation_rate": round(report.escalation_rate, 3),
        "feedback": report.feedback_breakdown,
        "worst_equipment": report.worst_performing_equipment,
        "knowledge_gaps": report.knowledge_gaps[:10],
    }


@router.get("/analytics/equipment-coverage")
async def get_equipment_coverage(
    analytics: RAGAnalytics = Depends(get_analytics),
) -> dict[str, Any]:
    """Analyze manual coverage by equipment brand/model."""
    return await analytics.get_equipment_coverage()


@router.get("/analytics/daily-metrics")
async def get_daily_metrics(
    days: int = Query(30, ge=1, le=90),
    analytics: RAGAnalytics = Depends(get_analytics),
) -> list[dict[str, Any]]:
    """Get daily metrics for trend analysis."""
    return await analytics.get_daily_metrics(days=days)


# Knowledge Gap Routes
@router.get("/knowledge-gaps")
async def get_knowledge_gaps(
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker),
) -> dict[str, Any]:
    """Get prioritized list of knowledge gaps."""
    gaps = await tracker.get_priority_gaps(limit=limit, status=status)
    stats = await tracker.get_stats()

    return {
        "gaps": gaps,
        "stats": stats,
    }


@router.get("/knowledge-gaps/{gap_id}")
async def get_knowledge_gap(
    gap_id: str,
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker),
) -> dict[str, Any]:
    """Get a specific knowledge gap by ID."""
    gap = await tracker.get_gap_by_id(gap_id)
    if not gap:
        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    return gap


@router.post("/knowledge-gaps/{gap_id}/resolve")
async def resolve_knowledge_gap(
    gap_id: str,
    request: GapResolutionRequest,
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker),
) -> dict[str, str]:
    """Mark a knowledge gap as resolved."""
    await tracker.mark_resolved(gap_id, request.resolution_notes)
    return {"status": "resolved", "gap_id": gap_id}


@router.post("/knowledge-gaps/{gap_id}/in-progress")
async def mark_gap_in_progress(
    gap_id: str,
    notes: str | None = None,
    tracker: KnowledgeGapTracker = Depends(get_gap_tracker),
) -> dict[str, str]:
    """Mark a knowledge gap as being worked on."""
    await tracker.mark_in_progress(gap_id, notes)
    return {"status": "in_progress", "gap_id": gap_id}


# Conversation Review Routes
@router.get("/conversations/flagged")
async def get_flagged_conversations(
    limit: int = Query(50, ge=1, le=200),
    redis: Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Get conversations flagged for review."""
    if not redis:
        return {"flagged_messages": [], "note": "Redis not available"}

    flagged_ids = await redis.smembers("review:flagged_messages")

    flagged = []
    for msg_id in list(flagged_ids)[:limit]:
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
        reason = await redis.hget(f"review:message:{msg_id_str}", "reason")
        reason_str = reason.decode() if isinstance(reason, bytes) else reason
        flagged.append({
            "message_id": msg_id_str,
            "flag_reason": reason_str,
        })

    return {"flagged_messages": flagged, "total": len(flagged_ids)}


@router.post("/conversations/{message_id}/annotate")
async def annotate_message(
    message_id: str,
    request: AnnotationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Annotate a message for training data quality."""
    result = await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(
            is_good_example=request.is_good_example,
            annotation_notes=request.notes,
            annotated_at=datetime.utcnow(),
        )
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()

    return {"status": "annotated", "message_id": message_id}


@router.delete("/conversations/flagged/{message_id}")
async def unflag_message(
    message_id: str,
    redis: Redis | None = Depends(get_redis),
) -> dict[str, str]:
    """Remove a message from the flagged list."""
    if not redis:
        raise HTTPException(status_code=503, detail="Redis not available")

    await redis.srem("review:flagged_messages", message_id)
    await redis.delete(f"review:message:{message_id}")

    return {"status": "unflagged", "message_id": message_id}


# Real-time Metrics Routes
@router.get("/realtime/metrics")
async def get_realtime_metrics(
    redis: Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Get real-time system metrics from Redis."""
    if not redis:
        return {
            "note": "Redis not available",
            "conversations_today": 0,
            "confidence_distribution": {},
            "latency_histogram": {},
            "escalations_today": 0,
            "feedback_by_type": {},
        }

    pipe = redis.pipeline()
    pipe.get("stats:conversations:today")
    pipe.hgetall("stats:confidence:distribution")
    pipe.hgetall("stats:latency:histogram")
    pipe.get("stats:escalations:today")
    pipe.hgetall("stats:feedback:by_type")

    results = await pipe.execute()

    def decode_dict(d):
        if not d:
            return {}
        return {
            (k.decode() if isinstance(k, bytes) else k): int(v.decode() if isinstance(v, bytes) else v)
            for k, v in d.items()
        }

    return {
        "conversations_today": int(results[0] or 0),
        "confidence_distribution": decode_dict(results[1]),
        "latency_histogram": decode_dict(results[2]),
        "escalations_today": int(results[3] or 0),
        "feedback_by_type": decode_dict(results[4]),
    }


@router.post("/realtime/reset-daily")
async def reset_daily_metrics(
    redis: Redis | None = Depends(get_redis),
) -> dict[str, str]:
    """Reset daily metrics counters."""
    if not redis:
        raise HTTPException(status_code=503, detail="Redis not available")

    await redis.delete(
        "stats:conversations:today",
        "stats:escalations:today",
    )

    return {"status": "reset"}


@router.get("/feedback/stats")
async def get_feedback_stats(
    db: AsyncSession = Depends(get_db),
    redis: Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Get feedback statistics including star ratings."""
    from sqlalchemy import select, func
    from models.conversation import MessageFeedback
    
    # Get rating distribution from database
    rating_query = select(
        MessageFeedback.rating,
        func.count(MessageFeedback.id).label("count")
    ).where(MessageFeedback.rating.isnot(None)).group_by(MessageFeedback.rating)
    
    result = await db.execute(rating_query)
    rating_distribution = {str(row.rating): row.count for row in result.all()}
    
    # Get feedback type distribution
    type_query = select(
        MessageFeedback.feedback_type,
        func.count(MessageFeedback.id).label("count")
    ).where(MessageFeedback.feedback_type.isnot(None)).group_by(MessageFeedback.feedback_type)
    
    result = await db.execute(type_query)
    type_distribution = {row.feedback_type: row.count for row in result.all()}
    
    # Calculate average rating
    avg_query = select(func.avg(MessageFeedback.rating)).where(MessageFeedback.rating.isnot(None))
    result = await db.execute(avg_query)
    avg_rating = result.scalar() or 0
    
    # Total feedback count
    total_query = select(func.count(MessageFeedback.id))
    result = await db.execute(total_query)
    total_feedback = result.scalar() or 0
    
    # Real-time stats from Redis
    realtime = {}
    if redis:
        pipe = redis.pipeline()
        pipe.hgetall("stats:feedback:by_rating")
        pipe.get("stats:feedback:rating_sum")
        pipe.get("stats:feedback:rating_count")
        results = await pipe.execute()
        
        realtime = {
            "by_rating": {
                (k.decode() if isinstance(k, bytes) else k): int(v.decode() if isinstance(v, bytes) else v)
                for k, v in (results[0] or {}).items()
            },
            "session_avg": float(results[1] or 0) / max(int(results[2] or 1), 1),
        }
    
    return {
        "total_feedback": total_feedback,
        "average_rating": round(float(avg_rating), 2),
        "rating_distribution": rating_distribution,
        "type_distribution": type_distribution,
        "realtime": realtime,
    }


# Fine-tuning Data Export Routes
@router.get("/finetuning/stats")
async def get_finetuning_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get statistics about available training data."""
    return await get_finetuning_statistics(db)


@router.post("/finetuning/export/embeddings")
async def export_embedding_training_data(
    min_retrieval_score: float = Query(0.7, ge=0, le=1),
    include_hard_negatives: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export training data for embedding model fine-tuning."""
    settings = get_settings()
    output_dir = Path(settings.data_dir) / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"embedding_training_{timestamp}.jsonl"

    exporter = TrainingDataExporter(db)
    stats = await exporter.export_embedding_data(
        output_path=output_path,
        min_retrieval_score=min_retrieval_score,
        include_hard_negatives=include_hard_negatives,
    )

    return {
        "status": "completed",
        "file_path": str(output_path),
        "statistics": stats,
    }


@router.post("/finetuning/export/reranker")
async def export_reranker_training_data(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export training data for reranker fine-tuning."""
    settings = get_settings()
    output_dir = Path(settings.data_dir) / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"reranker_training_{timestamp}.jsonl"

    exporter = TrainingDataExporter(db)
    stats = await exporter.export_reranker_data(output_path=output_path)

    return {
        "status": "completed",
        "file_path": str(output_path),
        "statistics": stats,
    }


@router.post("/finetuning/export/llm")
async def export_llm_training_data(
    format: str = Query("jsonl", pattern="^(jsonl|anthropic)$"),
    min_confidence: float = Query(0.8, ge=0, le=1),
    only_annotated: bool = False,
    only_resolved: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export training data for LLM fine-tuning."""
    settings = get_settings()
    output_dir = Path(settings.data_dir) / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"llm_finetuning_{timestamp}.jsonl"

    exporter = TrainingDataExporter(db)
    stats = await exporter.export_llm_finetuning_data(
        output_path=output_path,
        min_confidence=min_confidence,
        only_annotated=only_annotated,
        only_resolved=only_resolved,
        format=format,
    )

    return {
        "status": "completed",
        "file_path": str(output_path),
        "statistics": stats,
    }


@router.post("/finetuning/export/all")
async def export_all_training_data(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Export all types of training data."""
    settings = get_settings()
    output_dir = Path(settings.data_dir) / "exports"

    exporter = TrainingDataExporter(db)
    stats = await exporter.export_all(output_dir=output_dir, timestamp=True)

    return {
        "status": "completed",
        "output_directory": str(output_dir),
        "statistics": stats,
    }


# A/B Testing Experiment Routes
class CreateExperimentRequest(BaseModel):
    """Request to create an experiment."""

    name: str
    description: str = ""
    variants: list[dict[str, Any]]
    traffic_allocation: dict[str, float] | None = None


@router.get("/experiments")
async def list_experiments(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all experiments."""
    service = ABTestingService(db)
    if active_only:
        experiments = await service.get_active_experiments()
    else:
        from sqlalchemy import select
        from models.experiment import Experiment
        result = await db.execute(select(Experiment))
        experiments = result.scalars().all()

    return [
        {
            "id": str(exp.id),
            "name": exp.name,
            "description": exp.description,
            "is_active": exp.is_active,
            "variants": list(exp.variants.keys()),
            "start_date": exp.start_date.isoformat(),
            "end_date": exp.end_date.isoformat() if exp.end_date else None,
        }
        for exp in experiments
    ]


@router.get("/experiments/templates")
async def get_experiment_templates() -> dict[str, Any]:
    """Get available experiment templates."""
    return {
        name: {
            "name": template["name"],
            "description": template["description"],
            "variants": [v.name for v in template["variants"]],
        }
        for name, template in EXPERIMENT_TEMPLATES.items()
    }


@router.post("/experiments")
async def create_experiment(
    request: CreateExperimentRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new A/B experiment."""
    service = ABTestingService(db)

    variants = [
        VariantConfig(
            name=v["name"],
            config=v.get("config", {}),
            description=v.get("description", ""),
        )
        for v in request.variants
    ]

    experiment = await service.create_experiment(
        name=request.name,
        description=request.description,
        variants=variants,
        traffic_allocation=request.traffic_allocation,
    )

    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "status": "created",
    }


@router.post("/experiments/from-template/{template_name}")
async def create_experiment_from_template_route(
    template_name: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create an experiment from a predefined template."""
    from services.experiments import create_experiment_from_template

    if template_name not in EXPERIMENT_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template: {template_name}. Available: {list(EXPERIMENT_TEMPLATES.keys())}",
        )

    experiment = await create_experiment_from_template(db, template_name)

    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "status": "created",
    }


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get experiment details."""
    service = ABTestingService(db)
    experiment = await service.get_experiment(experiment_id)

    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    exposures = await service.get_experiment_exposures_count(experiment_id)

    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "description": experiment.description,
        "variants": experiment.variants,
        "traffic_allocation": experiment.traffic_allocation,
        "is_active": experiment.is_active,
        "start_date": experiment.start_date.isoformat(),
        "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
        "exposures_by_variant": exposures,
    }


@router.get("/experiments/{experiment_id}/analyze")
async def analyze_experiment(
    experiment_id: str,
    metric: str = Query("confidence_score"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Analyze experiment results."""
    service = ABTestingService(db)
    result = await service.analyze_experiment(experiment_id, metric_name=metric)

    return {
        "experiment_id": result.experiment_id,
        "experiment_name": result.experiment_name,
        "metric_analyzed": metric,
        "variants": result.variants,
        "winner": result.winner,
        "confidence": round(result.confidence, 3),
        "is_statistically_significant": result.is_significant,
        "sample_sizes": result.sample_sizes,
    }


@router.post("/experiments/{experiment_id}/end")
async def end_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """End an active experiment."""
    service = ABTestingService(db)
    experiment = await service.end_experiment(experiment_id)

    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "status": "ended",
        "end_date": experiment.end_date.isoformat(),
    }
