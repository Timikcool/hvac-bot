"""Knowledge gap detection and tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.analytics import KnowledgeGap


@dataclass
class DetectedGap:
    """A detected knowledge gap."""

    query_pattern: str
    equipment_context: dict[str, Any]
    occurrence_count: int
    avg_retrieval_score: float
    sample_queries: list[str] = field(default_factory=list)
    suggested_action: str = ""


class KnowledgeGapTracker:
    """Track and manage knowledge gaps over time."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def record_gap(self, gap: DetectedGap) -> str:
        """Record or update a knowledge gap.

        Args:
            gap: Detected gap data

        Returns:
            Gap ID
        """
        # Check if similar gap exists
        existing_query = select(KnowledgeGap).where(
            KnowledgeGap.query_pattern == gap.query_pattern
        )
        result = await self.db.execute(existing_query)
        existing_gap = result.scalar_one_or_none()

        if existing_gap:
            # Update existing
            existing_gap.occurrence_count += gap.occurrence_count
            existing_samples = existing_gap.sample_queries or []
            existing_gap.sample_queries = list(
                set(existing_samples + gap.sample_queries)
            )[:10]
            existing_gap.avg_retrieval_score = (
                existing_gap.avg_retrieval_score + gap.avg_retrieval_score
            ) / 2
            existing_gap.updated_at = datetime.utcnow()
            gap_id = existing_gap.id
        else:
            # Create new
            brands = gap.equipment_context.get("brands", [])
            models = gap.equipment_context.get("models", [])

            new_gap = KnowledgeGap(
                query_pattern=gap.query_pattern,
                equipment_brand=brands[0] if brands else None,
                equipment_model=models[0] if models else None,
                occurrence_count=gap.occurrence_count,
                sample_queries=gap.sample_queries,
                avg_retrieval_score=gap.avg_retrieval_score,
                status="identified",
                suggested_action=gap.suggested_action,
                metadata=gap.equipment_context,
            )
            self.db.add(new_gap)
            gap_id = new_gap.id

        await self.db.commit()
        return gap_id

    async def mark_resolved(
        self,
        gap_id: str,
        resolution_notes: str,
    ) -> None:
        """Mark a knowledge gap as resolved.

        Args:
            gap_id: Gap ID
            resolution_notes: Notes about resolution
        """
        await self.db.execute(
            update(KnowledgeGap)
            .where(KnowledgeGap.id == gap_id)
            .values(
                status="resolved",
                resolution_notes=resolution_notes,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.commit()

    async def mark_in_progress(
        self,
        gap_id: str,
        notes: str | None = None,
    ) -> None:
        """Mark a knowledge gap as being worked on.

        Args:
            gap_id: Gap ID
            notes: Optional progress notes
        """
        values = {
            "status": "in_progress",
            "updated_at": datetime.utcnow(),
        }
        if notes:
            values["resolution_notes"] = notes

        await self.db.execute(
            update(KnowledgeGap).where(KnowledgeGap.id == gap_id).values(**values)
        )
        await self.db.commit()

    async def get_priority_gaps(
        self,
        limit: int = 20,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get knowledge gaps prioritized by impact.

        Args:
            limit: Max results
            status: Optional status filter

        Returns:
            List of gap dicts
        """
        query = select(KnowledgeGap).order_by(
            KnowledgeGap.occurrence_count.desc(),
            KnowledgeGap.avg_retrieval_score.asc(),
        )

        if status:
            query = query.where(KnowledgeGap.status == status)
        else:
            query = query.where(KnowledgeGap.status != "resolved")

        query = query.limit(limit)

        result = await self.db.execute(query)
        gaps = result.scalars().all()

        return [
            {
                "id": g.id,
                "pattern": g.query_pattern,
                "brand": g.equipment_brand,
                "model": g.equipment_model,
                "occurrences": g.occurrence_count,
                "avg_score": g.avg_retrieval_score,
                "samples": (g.sample_queries or [])[:3],
                "status": g.status,
                "suggested_action": g.suggested_action,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            }
            for g in gaps
        ]

    async def get_gap_by_id(self, gap_id: str) -> dict[str, Any] | None:
        """Get a specific gap by ID.

        Args:
            gap_id: Gap ID

        Returns:
            Gap dict or None
        """
        query = select(KnowledgeGap).where(KnowledgeGap.id == gap_id)
        result = await self.db.execute(query)
        gap = result.scalar_one_or_none()

        if not gap:
            return None

        return {
            "id": gap.id,
            "pattern": gap.query_pattern,
            "brand": gap.equipment_brand,
            "model": gap.equipment_model,
            "occurrences": gap.occurrence_count,
            "avg_score": gap.avg_retrieval_score,
            "samples": gap.sample_queries or [],
            "status": gap.status,
            "suggested_action": gap.suggested_action,
            "resolution_notes": gap.resolution_notes,
            "metadata": gap.metadata,
            "created_at": gap.created_at.isoformat() if gap.created_at else None,
            "updated_at": gap.updated_at.isoformat() if gap.updated_at else None,
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get knowledge gap statistics."""
        from sqlalchemy import func

        # Count by status
        status_query = select(
            KnowledgeGap.status,
            func.count(KnowledgeGap.id),
        ).group_by(KnowledgeGap.status)

        result = await self.db.execute(status_query)
        by_status = {row[0]: row[1] for row in result.fetchall()}

        # Total occurrences
        total_query = select(func.sum(KnowledgeGap.occurrence_count))
        total_result = await self.db.execute(total_query)
        total_occurrences = total_result.scalar() or 0

        return {
            "total_gaps": sum(by_status.values()),
            "by_status": by_status,
            "total_occurrences": total_occurrences,
            "identified": by_status.get("identified", 0),
            "in_progress": by_status.get("in_progress", 0),
            "resolved": by_status.get("resolved", 0),
        }
