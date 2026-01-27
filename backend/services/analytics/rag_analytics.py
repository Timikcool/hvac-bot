"""RAG quality analytics service."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation, Message, MessageFeedback, MessageRetrieval


@dataclass
class RetrievalQualityReport:
    """Comprehensive RAG quality report."""

    period_start: datetime
    period_end: datetime
    total_queries: int
    avg_top_retrieval_score: float
    avg_response_confidence: float
    low_confidence_rate: float
    escalation_rate: float
    feedback_breakdown: dict[str, int] = field(default_factory=dict)
    worst_performing_equipment: list[dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: list[dict[str, Any]] = field(default_factory=list)


class RAGAnalytics:
    """Analyze RAG performance and identify knowledge gaps."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def generate_quality_report(
        self,
        start_date: datetime,
        end_date: datetime,
        equipment_brand: str | None = None,
    ) -> RetrievalQualityReport:
        """Generate comprehensive RAG quality report.

        Args:
            start_date: Report period start
            end_date: Report period end
            equipment_brand: Optional filter by brand

        Returns:
            RetrievalQualityReport with metrics
        """
        # Base query conditions
        conditions = [
            Message.role == "assistant",
            Message.created_at >= start_date,
            Message.created_at <= end_date,
        ]

        # Get basic metrics
        basic_stats_query = select(
            func.count(Message.id).label("total"),
            func.avg(Message.confidence_score).label("avg_confidence"),
            func.sum(case((Message.confidence_level == "low", 1), else_=0)).label(
                "low_confidence_count"
            ),
            func.sum(case((Message.required_escalation == True, 1), else_=0)).label(
                "escalation_count"
            ),
        ).where(and_(*conditions))

        basic_result = await self.db.execute(basic_stats_query)
        stats = basic_result.fetchone()

        total = stats.total or 0
        avg_confidence = float(stats.avg_confidence or 0)
        low_confidence_count = stats.low_confidence_count or 0
        escalation_count = stats.escalation_count or 0

        # Get average retrieval scores
        retrieval_query = (
            select(func.avg(MessageRetrieval.similarity_score))
            .join(Message, MessageRetrieval.message_id == Message.id)
            .where(
                and_(
                    Message.created_at >= start_date,
                    Message.created_at <= end_date,
                    MessageRetrieval.position_in_results == 0,  # Top result
                )
            )
        )
        retrieval_result = await self.db.execute(retrieval_query)
        avg_retrieval = float(retrieval_result.scalar() or 0)

        # Feedback breakdown
        feedback_query = (
            select(MessageFeedback.feedback_type, func.count(MessageFeedback.id))
            .join(Message, MessageFeedback.message_id == Message.id)
            .where(
                and_(
                    Message.created_at >= start_date,
                    Message.created_at <= end_date,
                )
            )
            .group_by(MessageFeedback.feedback_type)
        )
        feedback_result = await self.db.execute(feedback_query)
        feedback_breakdown = {row[0]: row[1] for row in feedback_result.fetchall()}

        # Worst performing equipment
        worst_equipment = await self._get_worst_performing_equipment(start_date, end_date)

        return RetrievalQualityReport(
            period_start=start_date,
            period_end=end_date,
            total_queries=total,
            avg_top_retrieval_score=avg_retrieval,
            avg_response_confidence=avg_confidence,
            low_confidence_rate=low_confidence_count / max(total, 1),
            escalation_rate=escalation_count / max(total, 1),
            feedback_breakdown=feedback_breakdown,
            worst_performing_equipment=worst_equipment,
            knowledge_gaps=[],  # Populated by KnowledgeGapTracker
        )

    async def _get_worst_performing_equipment(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find equipment with lowest retrieval/confidence scores."""
        query = text("""
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
        """)

        result = await self.db.execute(
            query,
            {"start_date": start_date, "end_date": end_date, "limit": limit},
        )

        return [
            {
                "brand": row.equipment_brand,
                "model": row.equipment_model,
                "query_count": row.query_count,
                "avg_confidence": float(row.avg_confidence or 0),
                "low_confidence_rate": row.low_confidence_count / row.query_count,
                "escalation_rate": row.escalation_count / row.query_count,
            }
            for row in result.fetchall()
        ]

    async def get_equipment_coverage(self) -> dict[str, Any]:
        """Analyze manual coverage by equipment brand/model."""
        # Get unique equipment from conversations
        conv_query = select(
            Conversation.equipment_brand,
            Conversation.equipment_model,
        ).where(Conversation.equipment_brand.isnot(None)).distinct()

        conv_result = await self.db.execute(conv_query)
        conv_equipment = {(r[0], r[1]) for r in conv_result.fetchall()}

        # Get equipment covered by manuals (from manual_metadata table)
        manual_query = text("""
            SELECT DISTINCT brand, model
            FROM manuals
            WHERE brand IS NOT NULL
        """)

        try:
            manual_result = await self.db.execute(manual_query)
            manual_equipment = {(r[0], r[1]) for r in manual_result.fetchall()}
        except Exception:
            manual_equipment = set()

        # Find gaps
        missing_coverage = conv_equipment - manual_equipment

        return {
            "total_equipment_seen": len(conv_equipment),
            "equipment_with_manuals": len(conv_equipment & manual_equipment),
            "equipment_without_manuals": len(missing_coverage),
            "missing_coverage": [
                {"brand": b, "model": m} for b, m in sorted(missing_coverage)
            ][:50],
        }

    async def get_daily_metrics(
        self,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get daily metrics for trend analysis."""
        query = text("""
            SELECT
                DATE(m.created_at) as date,
                COUNT(*) as query_count,
                AVG(m.confidence_score) as avg_confidence,
                SUM(CASE WHEN m.required_escalation THEN 1 ELSE 0 END) as escalations
            FROM messages m
            WHERE m.role = 'assistant'
                AND m.created_at >= NOW() - INTERVAL ':days days'
            GROUP BY DATE(m.created_at)
            ORDER BY date DESC
        """)

        result = await self.db.execute(query, {"days": days})

        return [
            {
                "date": row.date.isoformat() if row.date else None,
                "query_count": row.query_count,
                "avg_confidence": float(row.avg_confidence or 0),
                "escalations": row.escalations,
            }
            for row in result.fetchall()
        ]
