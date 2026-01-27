"""Fine-tuning data export service.

Exports training data in various formats for fine-tuning:
- Embedding models (positive pairs, hard negatives)
- Reranker models (query-document relevance)
- LLM fine-tuning (conversation format)
"""

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import (
    Conversation,
    Message,
    MessageFeedback,
    MessageRetrieval,
)


@dataclass
class EmbeddingTrainingSample:
    """A training sample for embedding models."""

    query: str
    positive_doc: str
    negative_docs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankerTrainingSample:
    """A training sample for reranker models."""

    query: str
    document: str
    relevance_score: float  # 0.0 to 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMTrainingSample:
    """A training sample for LLM fine-tuning."""

    system_prompt: str
    messages: list[dict[str, str]]  # role, content pairs
    metadata: dict[str, Any] = field(default_factory=dict)


class TrainingDataExporter:
    """Export training data for model fine-tuning.

    Extracts high-quality examples from conversations based on:
    - User feedback (helpful vs not helpful)
    - Retrieval quality scores
    - Manual annotations by admins
    - Resolution status
    """

    DEFAULT_SYSTEM_PROMPT = """You are an expert HVAC technician assistant. Answer questions about HVAC equipment troubleshooting, repair, and maintenance based on the provided documentation. Be precise, cite sources, and always prioritize safety."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def export_embedding_data(
        self,
        output_path: str | Path,
        min_retrieval_score: float = 0.7,
        include_hard_negatives: bool = True,
        format: str = "jsonl",
    ) -> dict[str, Any]:
        """Export training data for embedding model fine-tuning.

        Creates query-positive-negative triplets from successful retrievals.

        Args:
            output_path: Output file path
            min_retrieval_score: Minimum score for positive examples
            include_hard_negatives: Include documents that were retrieved but not used
            format: Output format (jsonl, csv)

        Returns:
            Export statistics
        """
        output_path = Path(output_path)
        samples: list[EmbeddingTrainingSample] = []

        # Get messages with good retrievals and positive feedback
        query = (
            select(Message, MessageRetrieval)
            .join(MessageRetrieval, Message.id == MessageRetrieval.message_id)
            .join(MessageFeedback, Message.id == MessageFeedback.message_id, isouter=True)
            .where(
                and_(
                    Message.role == "user",
                    MessageRetrieval.similarity_score >= min_retrieval_score,
                    MessageRetrieval.was_used_in_response == True,  # noqa: E712
                )
            )
        )

        result = await self.db.execute(query)
        rows = result.all()

        # Group by message to collect positive and negative docs
        message_docs: dict[str, dict[str, Any]] = {}

        for message, retrieval in rows:
            msg_id = str(message.id)
            if msg_id not in message_docs:
                message_docs[msg_id] = {
                    "query": message.content,
                    "positives": [],
                    "negatives": [],
                    "metadata": {
                        "conversation_id": str(message.conversation_id),
                        "detected_intent": message.detected_intent,
                    },
                }

            if retrieval.was_used_in_response and retrieval.similarity_score >= min_retrieval_score:
                message_docs[msg_id]["positives"].append(retrieval.chunk_content)
            elif include_hard_negatives and retrieval.similarity_score < min_retrieval_score:
                # Hard negatives: retrieved but not relevant enough
                message_docs[msg_id]["negatives"].append(retrieval.chunk_content)

        # Convert to training samples
        for msg_data in message_docs.values():
            if msg_data["positives"]:
                samples.append(
                    EmbeddingTrainingSample(
                        query=msg_data["query"],
                        positive_doc=msg_data["positives"][0],  # Primary positive
                        negative_docs=msg_data["negatives"][:5],  # Limit negatives
                        metadata=msg_data["metadata"],
                    )
                )

        # Write output
        stats = self._write_embedding_samples(samples, output_path, format)
        stats["total_samples"] = len(samples)
        return stats

    async def export_reranker_data(
        self,
        output_path: str | Path,
        format: str = "jsonl",
    ) -> dict[str, Any]:
        """Export training data for reranker model fine-tuning.

        Creates query-document pairs with relevance labels.

        Args:
            output_path: Output file path
            format: Output format (jsonl, csv)

        Returns:
            Export statistics
        """
        output_path = Path(output_path)
        samples: list[RerankerTrainingSample] = []

        # Get all retrievals with usage information
        query = (
            select(Message, MessageRetrieval)
            .join(MessageRetrieval, Message.id == MessageRetrieval.message_id)
            .where(Message.role == "user")
        )

        result = await self.db.execute(query)
        rows = result.all()

        for message, retrieval in rows:
            # Calculate relevance score based on multiple signals
            relevance = self._calculate_relevance_score(retrieval)

            samples.append(
                RerankerTrainingSample(
                    query=message.content,
                    document=retrieval.chunk_content,
                    relevance_score=relevance,
                    metadata={
                        "original_similarity": retrieval.similarity_score,
                        "rerank_score": retrieval.rerank_score,
                        "was_used": retrieval.was_used_in_response,
                        "position": retrieval.position_in_results,
                    },
                )
            )

        # Write output
        stats = self._write_reranker_samples(samples, output_path, format)
        stats["total_samples"] = len(samples)
        return stats

    async def export_llm_finetuning_data(
        self,
        output_path: str | Path,
        min_confidence: float = 0.7,
        only_annotated: bool = False,
        only_resolved: bool = True,
        format: str = "jsonl",
    ) -> dict[str, Any]:
        """Export training data for LLM fine-tuning.

        Creates conversation examples in chat format.

        Args:
            output_path: Output file path
            min_confidence: Minimum confidence score for assistant messages
            only_annotated: Only include manually annotated examples
            only_resolved: Only include resolved conversations
            format: Output format (jsonl, anthropic)

        Returns:
            Export statistics
        """
        output_path = Path(output_path)
        samples: list[LLMTrainingSample] = []

        # Build query based on filters
        conv_filters = []
        if only_resolved:
            conv_filters.append(Conversation.resolution_status == "resolved")

        query = select(Conversation)
        if conv_filters:
            query = query.where(and_(*conv_filters))

        result = await self.db.execute(query)
        conversations = result.scalars().all()

        for conv in conversations:
            # Get messages for this conversation
            msg_query = (
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at)
            )
            msg_result = await self.db.execute(msg_query)
            messages = msg_result.scalars().all()

            # Filter based on criteria
            valid_conversation = True
            formatted_messages = []

            for msg in messages:
                if msg.role == "assistant":
                    # Check confidence threshold
                    if msg.confidence_score and msg.confidence_score < min_confidence:
                        valid_conversation = False
                        break

                    # Check annotation filter
                    if only_annotated and not msg.is_good_example:
                        valid_conversation = False
                        break

                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })

            if valid_conversation and len(formatted_messages) >= 2:
                # Build context from equipment info
                context_parts = []
                if conv.equipment_brand:
                    context_parts.append(f"Equipment: {conv.equipment_brand}")
                if conv.equipment_model:
                    context_parts.append(f"Model: {conv.equipment_model}")
                if conv.system_type:
                    context_parts.append(f"System type: {conv.system_type}")

                system_prompt = self.DEFAULT_SYSTEM_PROMPT
                if context_parts:
                    system_prompt += f"\n\nContext: {', '.join(context_parts)}"

                samples.append(
                    LLMTrainingSample(
                        system_prompt=system_prompt,
                        messages=formatted_messages,
                        metadata={
                            "conversation_id": str(conv.id),
                            "resolution_status": conv.resolution_status,
                            "satisfaction_score": conv.user_satisfaction_score,
                            "equipment_brand": conv.equipment_brand,
                            "equipment_model": conv.equipment_model,
                        },
                    )
                )

        # Write output
        stats = self._write_llm_samples(samples, output_path, format)
        stats["total_samples"] = len(samples)
        return stats

    async def export_all(
        self,
        output_dir: str | Path,
        timestamp: bool = True,
    ) -> dict[str, Any]:
        """Export all training data types.

        Args:
            output_dir: Output directory
            timestamp: Add timestamp to filenames

        Returns:
            Combined export statistics
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S") if timestamp else ""
        suffix = f"_{ts}" if ts else ""

        stats = {}

        # Export embedding data
        embedding_path = output_dir / f"embedding_training{suffix}.jsonl"
        stats["embedding"] = await self.export_embedding_data(embedding_path)

        # Export reranker data
        reranker_path = output_dir / f"reranker_training{suffix}.jsonl"
        stats["reranker"] = await self.export_reranker_data(reranker_path)

        # Export LLM data
        llm_path = output_dir / f"llm_finetuning{suffix}.jsonl"
        stats["llm"] = await self.export_llm_finetuning_data(llm_path)

        return stats

    def _calculate_relevance_score(self, retrieval: MessageRetrieval) -> float:
        """Calculate relevance score for reranker training.

        Combines multiple signals into a single relevance score.
        """
        score = 0.0

        # Base score from similarity
        score += retrieval.similarity_score * 0.4

        # Boost if actually used in response
        if retrieval.was_used_in_response:
            score += 0.3

        # Boost from rerank score if available
        if retrieval.rerank_score:
            score += retrieval.rerank_score * 0.2

        # Position penalty (lower positions = less relevant)
        position_factor = max(0, 1 - (retrieval.position_in_results * 0.05))
        score += position_factor * 0.1

        return min(1.0, max(0.0, score))

    def _write_embedding_samples(
        self,
        samples: list[EmbeddingTrainingSample],
        path: Path,
        format: str,
    ) -> dict[str, Any]:
        """Write embedding samples to file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "jsonl":
            with open(path, "w") as f:
                for sample in samples:
                    record = {
                        "query": sample.query,
                        "positive": sample.positive_doc,
                        "negatives": sample.negative_docs,
                        "metadata": sample.metadata,
                    }
                    f.write(json.dumps(record) + "\n")
        elif format == "csv":
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["query", "positive", "negative_1", "negative_2", "negative_3"])
                for sample in samples:
                    negatives = sample.negative_docs[:3] + [""] * (3 - len(sample.negative_docs[:3]))
                    writer.writerow([sample.query, sample.positive_doc] + negatives)

        return {"output_path": str(path), "format": format}

    def _write_reranker_samples(
        self,
        samples: list[RerankerTrainingSample],
        path: Path,
        format: str,
    ) -> dict[str, Any]:
        """Write reranker samples to file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "jsonl":
            with open(path, "w") as f:
                for sample in samples:
                    record = {
                        "query": sample.query,
                        "document": sample.document,
                        "score": sample.relevance_score,
                        "metadata": sample.metadata,
                    }
                    f.write(json.dumps(record) + "\n")
        elif format == "csv":
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["query", "document", "relevance_score"])
                for sample in samples:
                    writer.writerow([sample.query, sample.document, sample.relevance_score])

        return {"output_path": str(path), "format": format}

    def _write_llm_samples(
        self,
        samples: list[LLMTrainingSample],
        path: Path,
        format: str,
    ) -> dict[str, Any]:
        """Write LLM training samples to file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "jsonl":
            with open(path, "w") as f:
                for sample in samples:
                    record = {
                        "system": sample.system_prompt,
                        "messages": sample.messages,
                        "metadata": sample.metadata,
                    }
                    f.write(json.dumps(record) + "\n")
        elif format == "anthropic":
            # Anthropic fine-tuning format
            with open(path, "w") as f:
                for sample in samples:
                    record = {
                        "system": sample.system_prompt,
                        "messages": [
                            {"role": m["role"], "content": m["content"]}
                            for m in sample.messages
                        ],
                    }
                    f.write(json.dumps(record) + "\n")

        return {"output_path": str(path), "format": format}


async def get_finetuning_statistics(db_session: AsyncSession) -> dict[str, Any]:
    """Get statistics about available training data.

    Returns counts and quality metrics for potential training data.
    """
    stats = {}

    # Count total conversations
    conv_count = await db_session.execute(select(Conversation))
    stats["total_conversations"] = len(conv_count.scalars().all())

    # Count resolved conversations
    resolved_count = await db_session.execute(
        select(Conversation).where(Conversation.resolution_status == "resolved")
    )
    stats["resolved_conversations"] = len(resolved_count.scalars().all())

    # Count annotated messages
    annotated_count = await db_session.execute(
        select(Message).where(Message.is_good_example == True)  # noqa: E712
    )
    stats["annotated_good_examples"] = len(annotated_count.scalars().all())

    # Count messages with high confidence
    high_conf_count = await db_session.execute(
        select(Message).where(
            and_(
                Message.role == "assistant",
                Message.confidence_score >= 0.8,
            )
        )
    )
    stats["high_confidence_responses"] = len(high_conf_count.scalars().all())

    # Count positive feedback
    positive_feedback = await db_session.execute(
        select(MessageFeedback).where(MessageFeedback.feedback_type == "helpful")
    )
    stats["positive_feedback_count"] = len(positive_feedback.scalars().all())

    # Count retrievals for embedding training
    retrieval_count = await db_session.execute(
        select(MessageRetrieval).where(MessageRetrieval.similarity_score >= 0.7)
    )
    stats["high_quality_retrievals"] = len(retrieval_count.scalars().all())

    return stats
