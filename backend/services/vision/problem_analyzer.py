"""Visual problem diagnosis service."""

from dataclasses import dataclass, field
from typing import Any

from core.llm import LLMClient


@dataclass
class VisualIssue:
    """A visually identified issue."""

    description: str
    evidence: str
    severity: str  # low, medium, high, critical
    confidence: float = 0.5


@dataclass
class VisualDiagnosis:
    """Result of visual problem analysis."""

    identified_components: list[str] = field(default_factory=list)
    visible_issues: list[VisualIssue] = field(default_factory=list)
    suggested_causes: list[str] = field(default_factory=list)
    recommended_checks: list[str] = field(default_factory=list)
    manual_references: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    requires_physical_inspection: bool = False
    safety_concerns: list[str] = field(default_factory=list)


class ProblemAnalyzer:
    """Analyze photos of HVAC equipment for visible issues.

    Cross-references visual findings with manual troubleshooting guides.
    """

    # Known visual patterns for common issues
    VISUAL_PATTERNS = {
        "frozen_evaporator": {
            "visual_cues": ["ice buildup", "frost on coil", "frozen lines"],
            "related_issues": ["low refrigerant", "airflow restriction", "faulty TXV"],
        },
        "burnt_contactor": {
            "visual_cues": ["pitting on contacts", "discoloration", "melted plastic"],
            "related_issues": ["contactor failure", "high amp draw", "voltage issues"],
        },
        "capacitor_failure": {
            "visual_cues": ["bulging top", "oil leak", "rust"],
            "related_issues": ["capacitor failed", "motor not starting"],
        },
        "condenser_coil_blockage": {
            "visual_cues": ["debris buildup", "bent fins", "cottonwood"],
            "related_issues": ["high head pressure", "poor cooling", "compressor overheating"],
        },
        "refrigerant_leak": {
            "visual_cues": ["oil stains", "green residue", "frost at one point"],
            "related_issues": ["refrigerant leak", "low charge"],
        },
        "burnt_wire": {
            "visual_cues": ["melted insulation", "discoloration", "charring"],
            "related_issues": ["loose connection", "overload", "short circuit"],
        },
        "motor_bearing_failure": {
            "visual_cues": ["shaft play", "scoring", "discoloration"],
            "related_issues": ["motor failure", "noise", "overheating"],
        },
    }

    def __init__(self, llm_client: LLMClient, retriever: Any = None):
        self.llm = llm_client
        self.retriever = retriever

    async def analyze_problem_image(
        self,
        image_data: bytes,
        user_description: str,
        equipment_context: dict[str, Any],
    ) -> VisualDiagnosis:
        """Analyze image of potential problem area.

        Args:
            image_data: Raw image bytes
            user_description: User's description of the issue
            equipment_context: Equipment brand/model context

        Returns:
            VisualDiagnosis with findings and recommendations
        """
        # Step 1: Get visual analysis from Claude
        visual_analysis = await self._get_visual_analysis(image_data, user_description)

        # Step 2: Cross-reference with manuals if retriever available
        manual_matches = []
        if self.retriever:
            manual_matches = await self._cross_reference_manuals(
                visual_analysis,
                equipment_context,
            )

        # Step 3: Build diagnosis
        diagnosis = self._build_diagnosis(visual_analysis, manual_matches)

        return diagnosis

    async def _get_visual_analysis(
        self,
        image_data: bytes,
        user_description: str,
    ) -> dict[str, Any]:
        """Use Claude vision to analyze the image."""
        prompt = f"""Analyze this HVAC equipment image for potential issues.

Technician's description: "{user_description}"

Provide analysis in JSON format:

{{
    "components_visible": ["list of HVAC components you can identify"],
    "condition_observations": [
        {{
            "component": "component name",
            "observation": "what you see",
            "condition": "normal/worn/damaged/failed",
            "confidence": 0.0-1.0
        }}
    ],
    "potential_issues": [
        {{
            "issue": "description of potential problem",
            "visual_evidence": "what specifically indicates this",
            "severity": "low/medium/high/critical"
        }}
    ],
    "image_quality": "good/acceptable/poor",
    "needs_closer_look": ["list of components needing better photos"],
    "safety_concerns": ["any visible safety issues"]
}}

IMPORTANT:
- Only identify what you can clearly see
- Don't diagnose issues that aren't visually evident
- Note when you're uncertain
- Flag any safety concerns immediately"""

        response = await self.llm.generate_with_vision(
            prompt=prompt,
            image_data=image_data,
            temperature=0,
        )

        return await self.llm.analyze_json(prompt=f"Extract JSON from: {response.content}")

    async def _cross_reference_manuals(
        self,
        visual_analysis: dict[str, Any],
        equipment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Cross-reference visual findings with manual troubleshooting guides."""
        if not self.retriever:
            return []

        matches = []

        for issue in visual_analysis.get("potential_issues", []):
            # Build search query from visual finding
            search_query = f"{issue.get('issue', '')} {issue.get('visual_evidence', '')}"

            # Add component context
            for component in visual_analysis.get("components_visible", []):
                if component.lower() in issue.get("issue", "").lower():
                    search_query += f" {component}"

            # Search manuals using retriever
            from services.rag.query_processor import ProcessedQuery

            processed = ProcessedQuery(
                original=search_query,
                enhanced=search_query,
                intent="diagnose",
                equipment_hints={},
                urgency="routine",
            )

            results = await self.retriever.retrieve(processed, equipment, top_k=3)

            if results.chunks:
                matches.append({
                    "visual_issue": issue.get("issue"),
                    "manual_references": [
                        {
                            "content": chunk["content"][:500],
                            "source": chunk.get("metadata", {}).get("manual_title"),
                            "page": chunk.get("metadata", {}).get("page_numbers"),
                            "relevance": chunk["score"],
                        }
                        for chunk in results.chunks
                    ],
                })

        return matches

    def _build_diagnosis(
        self,
        visual: dict[str, Any],
        manual_matches: list[dict[str, Any]],
    ) -> VisualDiagnosis:
        """Combine visual analysis with manual information."""
        visible_issues = []
        suggested_causes = []
        recommended_checks = []
        safety_concerns = []

        # Process visual issues
        for issue in visual.get("potential_issues", []):
            visible_issues.append(
                VisualIssue(
                    description=issue.get("issue", "Unknown issue"),
                    evidence=issue.get("visual_evidence", ""),
                    severity=issue.get("severity", "medium"),
                )
            )

        # Process manual matches
        for match in manual_matches:
            for ref in match.get("manual_references", []):
                content = ref.get("content", "").lower()
                if "cause" in content or "reason" in content:
                    suggested_causes.append(ref["content"][:200])
                if any(kw in content for kw in ["check", "inspect", "verify"]):
                    recommended_checks.append(ref["content"][:200])

        # Process safety concerns
        safety_concerns = visual.get("safety_concerns", [])

        # Determine if physical inspection is needed
        requires_inspection = (
            visual.get("image_quality") == "poor"
            or len(visual.get("needs_closer_look", [])) > 0
            or any(
                obs.get("confidence", 1) < 0.6
                for obs in visual.get("condition_observations", [])
            )
        )

        # Calculate overall confidence
        confidences = [
            obs.get("confidence", 0.5) for obs in visual.get("condition_observations", [])
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        return VisualDiagnosis(
            identified_components=visual.get("components_visible", []),
            visible_issues=visible_issues,
            suggested_causes=list(set(suggested_causes))[:5],
            recommended_checks=list(set(recommended_checks))[:5],
            manual_references=manual_matches,
            confidence=avg_confidence,
            requires_physical_inspection=requires_inspection,
            safety_concerns=safety_concerns,
        )

    async def compare_before_after(
        self,
        before_image: bytes,
        after_image: bytes,
        repair_description: str,
    ) -> dict[str, Any]:
        """Compare before/after images of a repair.

        Useful for documenting work completed.

        Args:
            before_image: Image before repair
            after_image: Image after repair
            repair_description: Description of work done

        Returns:
            Comparison analysis
        """
        # This would require multi-image support
        # For now, analyze each separately and compare
        before_analysis = await self._get_visual_analysis(
            before_image,
            f"Before: {repair_description}",
        )
        after_analysis = await self._get_visual_analysis(
            after_image,
            f"After: {repair_description}",
        )

        return {
            "before": before_analysis,
            "after": after_analysis,
            "improvements": self._compare_conditions(before_analysis, after_analysis),
        }

    def _compare_conditions(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> list[str]:
        """Compare before/after conditions."""
        improvements = []

        before_issues = {i.get("issue") for i in before.get("potential_issues", [])}
        after_issues = {i.get("issue") for i in after.get("potential_issues", [])}

        resolved = before_issues - after_issues
        for issue in resolved:
            improvements.append(f"Resolved: {issue}")

        return improvements
