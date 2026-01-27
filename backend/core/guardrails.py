"""Response validation and anti-hallucination guardrails."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.llm import LLMClient


class ViolationType(Enum):
    """Types of validation violations."""

    UNSUPPORTED_CLAIM = "unsupported_claim"
    FABRICATED_SPEC = "fabricated_spec"
    MISSING_CITATION = "missing_citation"
    SAFETY_OMISSION = "safety_omission"
    CONTRADICTION = "contradiction"


class ConfidenceLevel(Enum):
    """Confidence levels for responses."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class Violation:
    """A single validation violation."""

    type: ViolationType
    message: str
    severity: str = "medium"
    context: str | None = None


@dataclass
class ValidationResult:
    """Result of response validation."""

    is_valid: bool
    violations: list[Violation] = field(default_factory=list)
    corrected_response: str | None = None
    confidence_adjustment: float = 0.0


class ResponseValidator:
    """Validates generated responses against source material.

    Catches and corrects potential hallucinations before delivery.
    """

    # Patterns that often indicate hallucination
    SUSPICIOUS_PATTERNS = [
        r"\d+\s*(?:psi|PSI)\b",  # Specific pressure readings
        r"\d+\s*(?:degrees?|°)\s*[FC]",  # Specific temperatures
        r"\d+\s*(?:amps?|A)\b",  # Specific amp readings
        r"\d+\s*(?:volts?|V)\b",  # Specific voltages
        r"\d+\s*(?:ohms?|Ω)\b",  # Specific resistance
        r"\d+\s*(?:lbs?|oz|ounces?)\s+(?:of\s+)?(?:refrigerant|R-?\d+)",  # Refrigerant amounts
    ]

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def validate(
        self,
        response: str,
        source_chunks: list[dict[str, Any]],
        query: str,
    ) -> ValidationResult:
        """Validate response against source material.

        Args:
            response: Generated response to validate
            source_chunks: Retrieved source chunks
            query: Original user query

        Returns:
            ValidationResult with violations and optional correction
        """
        violations = []

        # Check 1: Verify all specific values appear in sources
        violations.extend(self._check_unsupported_values(response, source_chunks))

        # Check 2: Ensure citations are present and valid
        violations.extend(self._check_citations(response, source_chunks))

        # Check 3: Check for safety warning inclusion
        violations.extend(self._check_safety_warnings(response, source_chunks))

        # Check 4: Use Claude to verify factual grounding
        llm_violations = await self._llm_validation(response, source_chunks, query)
        violations.extend(llm_violations)

        # Determine if correction is needed
        corrected = None
        if violations:
            corrected = await self._generate_correction(response, violations, source_chunks)

        confidence_adjustment = -0.1 * len(violations)

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            corrected_response=corrected,
            confidence_adjustment=confidence_adjustment,
        )

    def _check_unsupported_values(
        self,
        response: str,
        sources: list[dict[str, Any]],
    ) -> list[Violation]:
        """Check if specific technical values in response exist in sources."""
        violations = []
        source_text = " ".join(s.get("content", "") for s in sources)

        for pattern in self.SUSPICIOUS_PATTERNS:
            matches = re.finditer(pattern, response, re.IGNORECASE)
            for match in matches:
                value = match.group()
                # Check if this value exists in sources
                if value.lower() not in source_text.lower():
                    # Allow some flexibility for format differences
                    normalized = re.sub(r"\s+", "", value.lower())
                    if normalized not in re.sub(r"\s+", "", source_text.lower()):
                        violations.append(
                            Violation(
                                type=ViolationType.FABRICATED_SPEC,
                                message=f"Value '{value}' not found in sources",
                                severity="high",
                                context=response[max(0, match.start() - 30) : match.end() + 30],
                            )
                        )

        return violations

    def _check_citations(
        self,
        response: str,
        sources: list[dict[str, Any]],
    ) -> list[Violation]:
        """Verify citations are present and reference real sources."""
        violations = []

        # Check for citation presence
        citations = re.findall(r"\[Source (\d+)\]", response)

        if not citations and len(response) > 200:
            violations.append(
                Violation(
                    type=ViolationType.MISSING_CITATION,
                    message="Response lacks source citations",
                    severity="medium",
                )
            )

        # Validate citation numbers
        for citation in citations:
            num = int(citation)
            if num < 1 or num > len(sources):
                violations.append(
                    Violation(
                        type=ViolationType.MISSING_CITATION,
                        message=f"Invalid citation [Source {num}]",
                        severity="high",
                    )
                )

        return violations

    def _check_safety_warnings(
        self,
        response: str,
        sources: list[dict[str, Any]],
    ) -> list[Violation]:
        """Ensure relevant safety warnings from sources are included."""
        violations = []

        # Find safety content in sources
        safety_keywords = ["warning", "caution", "danger", "hazard", "safety"]
        source_has_safety = False

        for source in sources:
            content = source.get("content", "").lower()
            if any(kw in content for kw in safety_keywords):
                source_has_safety = True
                break

        # If sources contain safety info but response doesn't mention safety
        if source_has_safety:
            response_lower = response.lower()
            if not any(kw in response_lower for kw in safety_keywords):
                violations.append(
                    Violation(
                        type=ViolationType.SAFETY_OMISSION,
                        message="Source contains safety warnings not reflected in response",
                        severity="high",
                    )
                )

        return violations

    async def _llm_validation(
        self,
        response: str,
        sources: list[dict[str, Any]],
        query: str,
    ) -> list[Violation]:
        """Use Claude to verify response is grounded in sources."""
        source_text = "\n---\n".join(s.get("content", "") for s in sources)

        validation_prompt = f"""Verify if this response is factually grounded in the source material.

SOURCES:
{source_text}

RESPONSE TO VERIFY:
{response}

ORIGINAL QUESTION:
{query}

Check for:
1. Any claims not supported by the sources
2. Specific values (temperatures, pressures, amperages) that don't appear in sources
3. Procedures or steps not described in sources
4. Contradictions with source material

Return JSON:
{{
    "is_grounded": true/false,
    "ungrounded_claims": [
        {{
            "claim": "the specific claim",
            "issue": "why it's not grounded"
        }}
    ]
}}

Be strict - if a specific technical value isn't in the sources, flag it."""

        result = await self.llm.analyze_json(prompt=validation_prompt)

        violations = []
        for claim in result.get("ungrounded_claims", []):
            violations.append(
                Violation(
                    type=ViolationType.UNSUPPORTED_CLAIM,
                    message=claim.get("issue", "Ungrounded claim"),
                    severity="medium",
                    context=claim.get("claim"),
                )
            )

        return violations

    async def _generate_correction(
        self,
        original: str,
        violations: list[Violation],
        sources: list[dict[str, Any]],
    ) -> str:
        """Generate corrected response addressing violations."""
        violation_summary = "\n".join(
            f"- {v.type.value}: {v.message}" for v in violations
        )

        source_text = "\n---\n".join(s.get("content", "") for s in sources)

        correction_prompt = f"""Correct this response to address the following issues:

ISSUES FOUND:
{violation_summary}

ORIGINAL RESPONSE:
{original}

AVAILABLE SOURCES:
{source_text}

Generate a corrected response that:
1. Removes or corrects any unsupported claims
2. Adds missing citations using [Source N] format
3. Includes relevant safety warnings
4. Clearly states when information is not available

If a specific value was flagged as fabricated, either:
- Find the correct value in the sources and cite it
- Remove the claim and note the information isn't in the available sources"""

        response = await self.llm.generate(
            prompt=correction_prompt,
            temperature=0.1,
        )

        return response.content


class ConfidenceScorer:
    """Calculate confidence scores for responses."""

    def calculate_score(
        self,
        response: str,
        retrieval_scores: list[float],
        validation_result: ValidationResult,
        query_type: str = "general",
    ) -> tuple[float, ConfidenceLevel]:
        """Calculate overall confidence score (0-1) and level.

        Factors:
        - Retrieval relevance scores
        - Validation result
        - Query type (specs need higher confidence)
        - Citation coverage
        """
        # Base score from retrieval
        if retrieval_scores:
            retrieval_score = sum(retrieval_scores) / len(retrieval_scores)
        else:
            retrieval_score = 0.0

        # Validation penalty
        validation_penalty = validation_result.confidence_adjustment

        # Citation coverage
        citation_count = len(re.findall(r"\[Source \d+\]", response))
        citation_score = min(1.0, citation_count / 3)  # At least 3 citations for full score

        # Query type modifier
        type_modifiers = {
            "find_spec": 0.9,  # Need high confidence for specs
            "understand_error": 0.85,
            "diagnose": 0.8,
            "general": 1.0,
        }
        type_modifier = type_modifiers.get(query_type, 0.9)

        # Combine scores
        raw_score = (
            retrieval_score * 0.4
            + citation_score * 0.3
            + (1 if validation_result.is_valid else 0.5) * 0.3
        )

        final_score = max(0.0, min(1.0, (raw_score + validation_penalty) * type_modifier))

        # Determine level
        if final_score >= 0.8:
            level = ConfidenceLevel.HIGH
        elif final_score >= 0.6:
            level = ConfidenceLevel.MEDIUM
        elif final_score >= 0.3:
            level = ConfidenceLevel.LOW
        else:
            level = ConfidenceLevel.NONE

        return final_score, level
