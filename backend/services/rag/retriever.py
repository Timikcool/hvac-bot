"""Multi-stage retrieval for HVAC queries."""

from dataclasses import dataclass, field
from typing import Any

from core.logging import get_logger
from services.rag.embedder import HVACEmbedder
from services.rag.query_processor import ProcessedQuery
from services.rag.vector_store import HVACVectorStore, SearchResult

logger = get_logger("rag.retriever")


@dataclass
class RetrievalResult:
    """Result of retrieval operation."""

    chunks: list[dict[str, Any]]
    total_found: int
    filters_applied: dict[str, Any]
    retrieval_strategy: str


class HVACRetriever:
    """Multi-stage retrieval optimized for HVAC technical queries.

    Uses query enhancement, filtering, and re-ranking.
    """

    def __init__(
        self,
        vector_store: HVACVectorStore,
        embedder: HVACEmbedder,
    ):
        self.vector_store = vector_store
        self.embedder = embedder

    async def retrieve(
        self,
        processed_query: ProcessedQuery,
        equipment_context: dict[str, Any],
        top_k: int = 10,
    ) -> RetrievalResult:
        """Multi-stage retrieval.

        1. Dense retrieval with filters
        2. Broaden search if needed
        3. Diversity sampling

        Args:
            processed_query: Processed query with metadata
            equipment_context: Equipment brand/model context
            top_k: Number of results to return

        Returns:
            RetrievalResult with ranked chunks
        """
        # Stage 1: Build filters from equipment context
        filters = self._build_filters(processed_query, equipment_context)
        logger.debug(f"RETRIEVER | Stage 1: Filters built | {filters}")

        # Stage 2: Dense retrieval (retrieve more than needed for diversity)
        logger.debug(f"RETRIEVER | Stage 2: Embedding query | length={len(processed_query.enhanced)}")
        query_embedding = await self.embedder.embed_query(
            processed_query.enhanced,
            equipment_context,
        )
        logger.debug(f"RETRIEVER | Query embedded | dim={len(query_embedding)}")

        initial_results = await self.vector_store.search(
            query_embedding=query_embedding,
            filters=filters,
            top_k=top_k * 3,  # Over-retrieve for diversity
        )
        logger.info(f"RETRIEVER | Stage 2: Initial search | found={len(initial_results)}")

        # Stage 3: If search yields few results, progressively broaden search
        if len(initial_results) < 5 and filters:
            logger.info(f"RETRIEVER | Stage 3: Broadening search (only {len(initial_results)} results)")
            
            # First, try removing chunk_type filter (too restrictive for general queries)
            if filters.get("chunk_type") and len(initial_results) < 3:
                broader_filters = {k: v for k, v in filters.items() if k != "chunk_type"}
                logger.debug(f"RETRIEVER | Removing chunk_type filter, trying: {broader_filters}")
                broader_results = await self.vector_store.search(
                    query_embedding=query_embedding,
                    filters=broader_filters if broader_filters else None,
                    top_k=top_k * 3,
                )
                seen_ids = {r.id for r in initial_results}
                for r in broader_results:
                    if r.id not in seen_ids:
                        initial_results.append(r)
                        seen_ids.add(r.id)
                logger.debug(f"RETRIEVER | After removing chunk_type: {len(initial_results)} results")
            
            # Then try removing model filter, keep brand
            if len(initial_results) < 5 and filters.get("model"):
                broader_filters = {k: v for k, v in filters.items() if k != "model" and k != "chunk_type"}
                broader_results = await self.vector_store.search(
                    query_embedding=query_embedding,
                    filters=broader_filters if broader_filters else None,
                    top_k=top_k * 2,
                )
                logger.debug(f"RETRIEVER | Broader search found {len(broader_results)} results")
                seen_ids = {r.id for r in initial_results}
                added = 0
                for r in broader_results:
                    if r.id not in seen_ids:
                        initial_results.append(r)
                        seen_ids.add(r.id)
                        added += 1
                logger.debug(f"RETRIEVER | Added {added} new results from broader search")
            
            # Finally, try with no filters at all
            if len(initial_results) < 3:
                logger.debug(f"RETRIEVER | Trying unfiltered search")
                unfiltered_results = await self.vector_store.search(
                    query_embedding=query_embedding,
                    filters=None,
                    top_k=top_k * 2,
                )
                seen_ids = {r.id for r in initial_results}
                for r in unfiltered_results:
                    if r.id not in seen_ids:
                        initial_results.append(r)
                        seen_ids.add(r.id)
                logger.debug(f"RETRIEVER | After unfiltered: {len(initial_results)} results")

        # Stage 4: Ensure diversity (don't return 5 chunks from same section)
        logger.debug(f"RETRIEVER | Stage 4: Ensuring diversity from {len(initial_results)} results")
        final_results = self._ensure_diversity(initial_results, max_per_section=2)

        # Limit to top_k
        final_results = final_results[:top_k]
        logger.info(f"RETRIEVER | Complete | returning {len(final_results)} chunks")

        if final_results:
            scores = [r.score for r in final_results]
            logger.debug(f"RETRIEVER | Score range: {min(scores):.3f} - {max(scores):.3f}")

        return RetrievalResult(
            chunks=[self._result_to_dict(r) for r in final_results],
            total_found=len(initial_results),
            filters_applied=filters,
            retrieval_strategy="dense_filtered",
        )

    def _build_filters(
        self,
        query: ProcessedQuery,
        equipment: dict[str, Any],
    ) -> dict[str, Any]:
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

    def _ensure_diversity(
        self,
        results: list[SearchResult],
        max_per_section: int = 2,
    ) -> list[SearchResult]:
        """Prevent over-representation from single manual section."""
        section_counts: dict[str, int] = {}
        diverse_results = []

        for result in results:
            section = result.metadata.get("parent_section", "unknown")
            if section_counts.get(section, 0) < max_per_section:
                diverse_results.append(result)
                section_counts[section] = section_counts.get(section, 0) + 1

        return diverse_results

    def _result_to_dict(self, result: SearchResult) -> dict[str, Any]:
        """Convert SearchResult to dict format."""
        return {
            "id": result.id,
            "content": result.content,
            "score": result.score,
            "metadata": result.metadata,
        }
