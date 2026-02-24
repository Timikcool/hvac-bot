"""Aggregate and analyze feedback corrections for system improvement."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from models.diagnostic import FeedbackCorrection, TerminologyMapping

logger = get_logger("improvement.feedback_aggregator")


class FeedbackAggregator:
    """Aggregate corrections and feedback to drive systematic improvements.

    Analyses patterns across multiple technician corrections to identify:
    - Terminology that consistently needs fixing
    - Diagnostic orderings that are consistently wrong
    - Missing information patterns
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def analyze_corrections(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """Aggregate corrections from the last N days.

        Returns summary statistics and actionable patterns.
        """
        since = datetime.utcnow() - timedelta(days=days)

        result = await self.db.execute(
            select(FeedbackCorrection).where(
                FeedbackCorrection.created_at >= since,
            )
        )
        corrections = result.scalars().all()

        if not corrections:
            return {
                "period_days": days,
                "total_corrections": 0,
                "by_type": {},
                "by_status": {},
                "terminology_patterns": [],
                "ordering_patterns": [],
            }

        # Count by type
        type_counts = Counter(c.correction_type for c in corrections)

        # Count by status
        status_counts = Counter(c.status for c in corrections)

        # Aggregate terminology corrections
        terminology_patterns = self._aggregate_terminology(corrections)

        # Aggregate ordering corrections
        ordering_patterns = self._aggregate_ordering(corrections)

        return {
            "period_days": days,
            "total_corrections": len(corrections),
            "by_type": dict(type_counts),
            "by_status": dict(status_counts),
            "terminology_patterns": terminology_patterns,
            "ordering_patterns": ordering_patterns,
            "most_common_type": type_counts.most_common(1)[0] if type_counts else None,
            "pending_count": status_counts.get("pending", 0),
            "applied_count": status_counts.get("applied", 0),
        }

    def _aggregate_terminology(
        self,
        corrections: list[FeedbackCorrection],
    ) -> list[dict[str, Any]]:
        """Find terminology corrections that appear multiple times."""
        term_corrections: dict[str, dict[str, Any]] = {}

        for c in corrections:
            if c.correction_type != "wrong_terminology":
                continue
            term_fix = (c.correction_data or {}).get("terminology_fix")
            if not term_fix:
                continue

            wrong = (term_fix.get("wrong_term") or "").lower().strip()
            correct = (term_fix.get("correct_term") or "").lower().strip()

            if not wrong or not correct:
                continue

            key = f"{wrong}→{correct}"
            if key not in term_corrections:
                term_corrections[key] = {
                    "wrong_term": wrong,
                    "correct_term": correct,
                    "count": 0,
                    "statuses": [],
                }
            term_corrections[key]["count"] += 1
            term_corrections[key]["statuses"].append(c.status)

        # Sort by frequency
        patterns = sorted(
            term_corrections.values(),
            key=lambda x: x["count"],
            reverse=True,
        )

        return patterns[:20]

    def _aggregate_ordering(
        self,
        corrections: list[FeedbackCorrection],
    ) -> list[dict[str, Any]]:
        """Find ordering corrections that appear multiple times."""
        ordering_corrections: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "should_be_first": "", "was_first": "", "flowchart_ids": set()}
        )

        for c in corrections:
            if c.correction_type != "wrong_order":
                continue
            ordering = (c.correction_data or {}).get("ordering_fix")
            if not ordering:
                continue

            should_first = (ordering.get("component_should_be_first") or "").lower().strip()
            was_first = (ordering.get("component_was_first") or "").lower().strip()

            if not should_first:
                continue

            key = f"{should_first}>{was_first}" if was_first else should_first
            entry = ordering_corrections[key]
            entry["count"] += 1
            entry["should_be_first"] = should_first
            entry["was_first"] = was_first
            if c.flowchart_id:
                entry["flowchart_ids"].add(c.flowchart_id)

        # Convert sets to lists for JSON
        patterns = []
        for entry in ordering_corrections.values():
            entry["flowchart_ids"] = list(entry["flowchart_ids"])
            patterns.append(dict(entry))

        patterns.sort(key=lambda x: x["count"], reverse=True)
        return patterns[:20]

    async def suggest_flowchart_updates(self) -> list[dict[str, Any]]:
        """Identify flowcharts where multiple techs corrected the same ordering.

        Returns suggestions for flowchart weight adjustments.
        """
        result = await self.db.execute(
            select(FeedbackCorrection).where(
                and_(
                    FeedbackCorrection.correction_type == "wrong_order",
                    FeedbackCorrection.status == "pending",
                    FeedbackCorrection.flowchart_id.isnot(None),
                )
            )
        )
        corrections = result.scalars().all()

        # Group by flowchart_id
        by_flowchart: dict[str, list[FeedbackCorrection]] = defaultdict(list)
        for c in corrections:
            if c.flowchart_id:
                by_flowchart[c.flowchart_id].append(c)

        suggestions = []
        for flowchart_id, corrs in by_flowchart.items():
            if len(corrs) < 2:
                continue

            # Find consensus among corrections
            component_votes: Counter = Counter()
            for c in corrs:
                ordering = (c.correction_data or {}).get("ordering_fix", {})
                comp = ordering.get("component_should_be_first", "")
                if comp:
                    component_votes[comp.lower()] += 1

            if component_votes:
                top_component, vote_count = component_votes.most_common(1)[0]
                suggestions.append({
                    "flowchart_id": flowchart_id,
                    "suggested_first_check": top_component,
                    "technician_agreement_count": vote_count,
                    "total_corrections": len(corrs),
                    "confidence": vote_count / len(corrs),
                })

        suggestions.sort(key=lambda s: s["technician_agreement_count"], reverse=True)
        return suggestions

    async def suggest_terminology_updates(self) -> list[dict[str, Any]]:
        """Identify terms frequently corrected that aren't yet in the mapping."""
        result = await self.db.execute(
            select(FeedbackCorrection).where(
                and_(
                    FeedbackCorrection.correction_type == "wrong_terminology",
                    FeedbackCorrection.status == "pending",
                )
            )
        )
        corrections = result.scalars().all()

        # Aggregate
        term_map: dict[str, dict[str, Any]] = {}
        for c in corrections:
            term_fix = (c.correction_data or {}).get("terminology_fix")
            if not term_fix:
                continue
            wrong = (term_fix.get("wrong_term") or "").lower().strip()
            correct = (term_fix.get("correct_term") or "").lower().strip()
            if not wrong or not correct:
                continue

            key = f"{wrong}→{correct}"
            if key not in term_map:
                term_map[key] = {
                    "textbook_term": wrong,
                    "field_term": correct,
                    "correction_count": 0,
                    "correction_ids": [],
                }
            term_map[key]["correction_count"] += 1
            term_map[key]["correction_ids"].append(c.id)

        # Check which are already in the terminology mapping
        existing_result = await self.db.execute(select(TerminologyMapping))
        existing = {m.textbook_term.lower() for m in existing_result.scalars().all()}

        suggestions = []
        for entry in term_map.values():
            if entry["textbook_term"] not in existing and entry["correction_count"] >= 2:
                suggestions.append({
                    **entry,
                    "already_mapped": False,
                    "recommendation": "add_mapping",
                })
            elif entry["textbook_term"] in existing and entry["correction_count"] >= 3:
                suggestions.append({
                    **entry,
                    "already_mapped": True,
                    "recommendation": "verify_mapping",
                })

        suggestions.sort(key=lambda s: s["correction_count"], reverse=True)
        return suggestions

    async def generate_report(self, days: int = 7) -> str:
        """Generate a human-readable weekly improvement summary."""
        analysis = await self.analyze_corrections(days=days)
        flowchart_suggestions = await self.suggest_flowchart_updates()
        terminology_suggestions = await self.suggest_terminology_updates()

        lines = [
            f"# Self-Improvement Report ({days}-day window)",
            f"",
            f"## Correction Summary",
            f"- Total corrections received: {analysis['total_corrections']}",
            f"- Applied: {analysis.get('applied_count', 0)}",
            f"- Pending review: {analysis.get('pending_count', 0)}",
            f"",
        ]

        if analysis["by_type"]:
            lines.append("## Corrections by Type")
            for ctype, count in sorted(
                analysis["by_type"].items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"- {ctype}: {count}")
            lines.append("")

        if analysis["terminology_patterns"]:
            lines.append("## Frequent Terminology Corrections")
            for tp in analysis["terminology_patterns"][:10]:
                lines.append(
                    f"- '{tp['wrong_term']}' → '{tp['correct_term']}' "
                    f"(reported {tp['count']}x)"
                )
            lines.append("")

        if analysis["ordering_patterns"]:
            lines.append("## Frequent Ordering Corrections")
            for op in analysis["ordering_patterns"][:10]:
                lines.append(
                    f"- '{op['should_be_first']}' should be checked first "
                    f"(reported {op['count']}x)"
                )
            lines.append("")

        if flowchart_suggestions:
            lines.append("## Suggested Flowchart Updates")
            for fs in flowchart_suggestions[:5]:
                lines.append(
                    f"- Flowchart {fs['flowchart_id'][:8]}...: "
                    f"Move '{fs['suggested_first_check']}' to first check "
                    f"({fs['technician_agreement_count']} techs agree)"
                )
            lines.append("")

        if terminology_suggestions:
            lines.append("## Suggested Terminology Additions")
            for ts in terminology_suggestions[:5]:
                action = "Add new" if not ts["already_mapped"] else "Verify existing"
                lines.append(
                    f"- {action} mapping: '{ts['textbook_term']}' → '{ts['field_term']}' "
                    f"({ts['correction_count']} corrections)"
                )
            lines.append("")

        if not analysis["total_corrections"]:
            lines.append("_No corrections received in this period._")

        return "\n".join(lines)
