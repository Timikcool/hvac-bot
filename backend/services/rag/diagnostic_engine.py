"""Diagnostic flowchart engine for probability-ordered troubleshooting.

Provides structured diagnostic paths ordered by failure probability,
supplementing RAG retrieval with expert-curated flowchart logic.
"""

from typing import Any, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.logging import get_logger
from models.diagnostic import DiagnosticFlowchart, DiagnosticStep

logger = get_logger("rag.diagnostic_engine")


class DiagnosticEngine:
    """Manages diagnostic flowcharts and probability-ordered troubleshooting.

    Works alongside RAG retrieval to provide structured diagnostic paths
    that order checks by failure likelihood (most common cause first).
    """

    def __init__(self, db_session: AsyncSession | None = None):
        self.db = db_session

    async def find_flowcharts(
        self,
        symptom: str,
        equipment_context: dict[str, Any],
        limit: int = 3,
    ) -> list[DiagnosticFlowchart]:
        """Find diagnostic flowcharts matching a symptom and equipment.

        Search strategy:
        1. Exact equipment match (brand + model)
        2. Brand-only match
        3. Generic match (no equipment filter)
        4. Keyword matching on symptom_keywords

        Args:
            symptom: User-described symptom text
            equipment_context: Equipment brand/model/system_type
            limit: Max flowcharts to return

        Returns:
            List of matching DiagnosticFlowchart with steps loaded
        """
        if not self.db:
            logger.warning("DIAGNOSTIC | No database session available")
            return []

        symptom_lower = symptom.lower()
        brand = equipment_context.get("brand")
        model = equipment_context.get("model")
        system_type = equipment_context.get("system_type")

        results = []

        # Strategy 1: Exact equipment match
        if brand and model:
            exact = await self._search_flowcharts(
                symptom_lower, brand=brand, model=model, limit=limit
            )
            results.extend(exact)

        # Strategy 2: Brand-only match
        if brand and len(results) < limit:
            brand_results = await self._search_flowcharts(
                symptom_lower, brand=brand, limit=limit - len(results)
            )
            seen_ids = {r.id for r in results}
            results.extend(r for r in brand_results if r.id not in seen_ids)

        # Strategy 3: System type match
        if system_type and len(results) < limit:
            type_results = await self._search_flowcharts(
                symptom_lower, system_type=system_type, limit=limit - len(results)
            )
            seen_ids = {r.id for r in results}
            results.extend(r for r in type_results if r.id not in seen_ids)

        # Strategy 4: Generic (no equipment filter)
        if len(results) < limit:
            generic = await self._search_flowcharts(
                symptom_lower, limit=limit - len(results)
            )
            seen_ids = {r.id for r in results}
            results.extend(r for r in generic if r.id not in seen_ids)

        logger.info(
            f"DIAGNOSTIC | Found {len(results)} flowcharts for symptom='{symptom[:50]}' "
            f"equipment={brand}/{model}"
        )

        return results[:limit]

    async def _search_flowcharts(
        self,
        symptom_lower: str,
        brand: Optional[str] = None,
        model: Optional[str] = None,
        system_type: Optional[str] = None,
        limit: int = 3,
    ) -> list[DiagnosticFlowchart]:
        """Search flowcharts with optional equipment filters."""
        conditions = [DiagnosticFlowchart.is_active == True]  # noqa: E712

        if brand:
            conditions.append(
                DiagnosticFlowchart.equipment_brand.ilike(f"%{brand}%")
            )
        if model:
            conditions.append(
                DiagnosticFlowchart.equipment_model.ilike(f"%{model}%")
            )
        if system_type:
            conditions.append(
                DiagnosticFlowchart.system_type.ilike(f"%{system_type}%")
            )

        # Keyword matching on symptom
        symptom_words = [w for w in symptom_lower.split() if len(w) > 3]
        if symptom_words:
            # Match symptom text or keywords
            symptom_conditions = []
            for word in symptom_words[:5]:
                symptom_conditions.append(
                    DiagnosticFlowchart.symptom.ilike(f"%{word}%")
                )
            if symptom_conditions:
                from sqlalchemy import or_

                conditions.append(or_(*symptom_conditions))

        try:
            result = await self.db.execute(
                select(DiagnosticFlowchart)
                .options(selectinload(DiagnosticFlowchart.steps))
                .where(and_(*conditions))
                .order_by(DiagnosticFlowchart.usage_count.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"DIAGNOSTIC | Search error: {e}")
            return []

    def get_ordered_steps(
        self, flowchart: DiagnosticFlowchart
    ) -> list[DiagnosticStep]:
        """Return steps sorted by priority_weight DESC (most likely cause first)."""
        active_steps = [s for s in flowchart.steps if s.is_active]
        return sorted(active_steps, key=lambda s: s.priority_weight, reverse=True)

    def format_for_prompt(self, flowchart: DiagnosticFlowchart) -> str:
        """Format a diagnostic flowchart as structured text for LLM prompt injection.

        This becomes part of the context the LLM uses to structure its response.
        """
        steps = self.get_ordered_steps(flowchart)
        if not steps:
            return ""

        lines = [
            f"DIAGNOSTIC FLOWCHART: {flowchart.symptom}",
            f"(Checks ordered by probability — most likely cause first)",
            "",
        ]

        for i, step in enumerate(steps, 1):
            lines.append(f"Step {i} (priority: {step.priority_weight}/100):")
            lines.append(f"  CHECK: {step.check_description}")
            if step.component:
                lines.append(f"  COMPONENT: {step.component}")
            if step.expected_result:
                lines.append(f"  EXPECTED: {step.expected_result}")
            if step.if_fail_action:
                lines.append(f"  IF FAILED: {step.if_fail_action}")
            if step.if_pass_action:
                lines.append(f"  IF OK: {step.if_pass_action}")
            if step.safety_warning:
                lines.append(f"  ⚠️ SAFETY: {step.safety_warning}")
            if step.tools_needed:
                lines.append(f"  TOOLS: {step.tools_needed}")
            lines.append("")

        return "\n".join(lines)

    def format_multiple_for_prompt(
        self, flowcharts: list[DiagnosticFlowchart]
    ) -> str:
        """Format multiple flowcharts for prompt injection."""
        if not flowcharts:
            return ""

        sections = []
        for fc in flowcharts:
            formatted = self.format_for_prompt(fc)
            if formatted:
                sections.append(formatted)

        if not sections:
            return ""

        header = (
            "DIAGNOSTIC GUIDANCE (from expert-curated flowcharts):\n"
            "Use these probability-ordered checks to structure your response.\n"
            "Present the most likely cause FIRST.\n\n"
        )
        return header + "\n---\n".join(sections)

    async def update_step_weight(
        self,
        step_id: str,
        delta: int,
        confirmed: bool = True,
    ) -> None:
        """Adjust a step's priority weight based on technician feedback.

        Args:
            step_id: The diagnostic step ID
            delta: Weight adjustment (+10 for confirmed, -10 for corrected)
            confirmed: Whether the tech confirmed this step was correct
        """
        if not self.db:
            return

        try:
            result = await self.db.execute(
                select(DiagnosticStep).where(DiagnosticStep.id == step_id)
            )
            step = result.scalar_one_or_none()
            if step:
                step.priority_weight = max(0, min(100, step.priority_weight + delta))
                if confirmed:
                    step.times_confirmed += 1
                else:
                    step.times_corrected += 1
                await self.db.commit()
                logger.info(
                    f"DIAGNOSTIC | Updated step {step_id} weight by {delta} "
                    f"→ {step.priority_weight}"
                )
        except Exception as e:
            logger.error(f"DIAGNOSTIC | Failed to update step weight: {e}")

    async def increment_usage(self, flowchart_id: str) -> None:
        """Track that a flowchart was used in a response."""
        if not self.db:
            return

        try:
            result = await self.db.execute(
                select(DiagnosticFlowchart).where(
                    DiagnosticFlowchart.id == flowchart_id
                )
            )
            fc = result.scalar_one_or_none()
            if fc:
                fc.usage_count += 1
                await self.db.commit()
        except Exception as e:
            logger.error(f"DIAGNOSTIC | Failed to increment usage: {e}")

    def get_step_components(
        self, flowchart: DiagnosticFlowchart
    ) -> list[str]:
        """Extract component names from a flowchart's steps for retrieval boosting."""
        components = []
        for step in self.get_ordered_steps(flowchart):
            if step.component:
                components.append(step.component.lower())
        return components
