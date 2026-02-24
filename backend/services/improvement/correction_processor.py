"""Process in-chat corrections from technicians to improve the system."""

from __future__ import annotations

import re
from typing import Any, Optional

from core.llm import LLMClient
from core.logging import get_logger
from models.diagnostic import FeedbackCorrection

logger = get_logger("improvement.correction_processor")

# Patterns that indicate a user is correcting the bot
CORRECTION_PATTERNS = [
    r"(?:that'?s|that is)\s+(?:wrong|incorrect|not right|not correct)",
    r"(?:no|nah|nope),?\s+(?:you should|check|it's|it should|the)",
    r"actually,?\s+(?:you should|we|it's|the|check)",
    r"(?:wrong|incorrect) order",
    r"order is (?:wrong|incorrect|not right)",
    r"should (?:be\s+\w+\s+|check\s+|look at\s+)?(?:first|before)",
    r"we (?:call|say|use)\s+(?:that|it|this)",
    r"(?:it's|it is|that's|that is)\s+called",
    r"(?:not|never)\s+(?:called|referred to as)",
    r"you got (?:it|that) (?:backwards|wrong|mixed up)",
    r"in the field,?\s+we",
    r"real techs?\s+(?:would|call|say|check)",
    r"most (?:likely|common)\s+(?:cause|issue|problem)\s+is",
]


class CorrectionProcessor:
    """Detect and process in-chat corrections from technicians.

    When a technician says something like "that's wrong, you should check
    the capacitor first", this class:
    1. Detects that it's a correction
    2. Extracts what was wrong and what's correct
    3. Applies the correction (terminology or ordering)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        db_session: Any = None,
    ):
        self.llm = llm_client
        self.db = db_session
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in CORRECTION_PATTERNS
        ]

    def detect_correction(self, message: str) -> bool:
        """Check if a user message is a correction of the bot's response.

        Uses pattern matching first (fast), then LLM for ambiguous cases.
        """
        message_lower = message.lower().strip()

        # Quick pattern check
        for pattern in self._compiled_patterns:
            if pattern.search(message_lower):
                logger.debug(f"CORRECTION | Pattern match detected: {pattern.pattern}")
                return True

        # Short messages that start with "no" are often corrections
        if message_lower.startswith("no") and len(message.split()) < 30:
            return True

        return False

    async def detect_correction_llm(
        self,
        message: str,
        previous_response: str,
    ) -> bool:
        """Use LLM to detect if message is a correction (for ambiguous cases)."""
        prompt = f"""Is the user correcting or disagreeing with the assistant's previous response?

ASSISTANT'S RESPONSE:
{previous_response[:500]}

USER'S MESSAGE:
{message}

Answer with ONLY "yes" or "no"."""

        result = await self.llm.generate(
            prompt=prompt,
            temperature=0.0,
            max_tokens=10,
        )
        return result.content.strip().lower().startswith("yes")

    async def extract_correction(
        self,
        message: str,
        previous_response: str,
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> FeedbackCorrection | None:
        """Extract structured correction data from a user message.

        Returns a FeedbackCorrection object or None if extraction fails.
        """
        prompt = f"""A technician is correcting an HVAC assistant's response. Extract the correction details.

ASSISTANT'S PREVIOUS RESPONSE:
{previous_response[:800]}

TECHNICIAN'S CORRECTION:
{message}

Extract in JSON format:
{{
    "correction_type": "wrong_order" | "wrong_terminology" | "missing_step" | "wrong_info" | "other",
    "original_text": "what the assistant said that was wrong (quote from response)",
    "corrected_text": "what the technician says is correct",
    "terminology_fix": {{
        "wrong_term": "term the assistant used incorrectly (if applicable)",
        "correct_term": "term the technician prefers"
    }} or null,
    "ordering_fix": {{
        "component_should_be_first": "component that should be checked first",
        "component_was_first": "component that was incorrectly listed first"
    }} or null,
    "missing_step": "description of step that was missing" or null,
    "confidence": 0.0-1.0
}}"""

        analysis = await self.llm.analyze_json(prompt=prompt)

        if not analysis or analysis.get("confidence", 0) < 0.3:
            logger.warning("CORRECTION | Low confidence extraction, skipping")
            return None

        correction_type = analysis.get("correction_type", "other")

        correction = FeedbackCorrection(
            message_id=message_id,
            conversation_id=conversation_id,
            correction_type=correction_type,
            original_text=analysis.get("original_text"),
            corrected_text=analysis.get("corrected_text"),
            correction_data={
                "terminology_fix": analysis.get("terminology_fix"),
                "ordering_fix": analysis.get("ordering_fix"),
                "missing_step": analysis.get("missing_step"),
                "extraction_confidence": analysis.get("confidence", 0.5),
            },
            status="pending",
        )

        logger.info(
            f"CORRECTION | Extracted correction | type={correction_type} | "
            f"confidence={analysis.get('confidence', 0):.2f}"
        )

        return correction

    async def apply_terminology_correction(
        self,
        correction: FeedbackCorrection,
        terminology_mapper: Any,
    ) -> bool:
        """Apply a terminology correction to the TerminologyMapper.

        Returns True if successfully applied.
        """
        term_fix = (correction.correction_data or {}).get("terminology_fix")
        if not term_fix:
            return False

        wrong_term = term_fix.get("wrong_term", "").strip()
        correct_term = term_fix.get("correct_term", "").strip()

        if not wrong_term or not correct_term:
            return False

        await terminology_mapper.add_mapping(
            textbook_term=wrong_term,
            field_term=correct_term,
            context="technician_correction",
        )

        correction.status = "applied"
        logger.info(
            f"CORRECTION | Applied terminology fix: '{wrong_term}' -> '{correct_term}'"
        )

        return True

    async def apply_ordering_correction(
        self,
        correction: FeedbackCorrection,
        diagnostic_engine: Any,
        flowchart_id: str | None = None,
    ) -> bool:
        """Apply an ordering correction to diagnostic step weights.

        Boosts the step the technician says should be first, penalizes
        the step that was incorrectly first.
        """
        ordering_fix = (correction.correction_data or {}).get("ordering_fix")
        if not ordering_fix:
            return False

        should_be_first = ordering_fix.get("component_should_be_first", "").strip()
        was_first = ordering_fix.get("component_was_first", "").strip()

        if not should_be_first:
            return False

        target_flowchart_id = flowchart_id or correction.flowchart_id
        if not target_flowchart_id:
            logger.warning("CORRECTION | No flowchart_id available for ordering correction")
            return False

        # Boost the correct component's step and penalize the wrong one
        steps = await diagnostic_engine.get_ordered_steps_by_flowchart_id(
            target_flowchart_id
        )

        applied = False
        for step in steps:
            component_lower = (step.component or "").lower()
            if should_be_first.lower() in component_lower:
                await diagnostic_engine.update_step_weight(step.id, delta=10)
                applied = True
                logger.info(
                    f"CORRECTION | Boosted step '{step.component}' weight +10"
                )
            elif was_first and was_first.lower() in component_lower:
                await diagnostic_engine.update_step_weight(step.id, delta=-5)
                logger.info(
                    f"CORRECTION | Reduced step '{step.component}' weight -5"
                )

        if applied:
            correction.status = "applied"

        return applied

    def generate_acknowledgment(self, correction: FeedbackCorrection) -> str:
        """Generate an acknowledgment message for the correction."""
        correction_type = correction.correction_type

        if correction_type == "wrong_terminology":
            term_fix = (correction.correction_data or {}).get("terminology_fix", {})
            wrong = term_fix.get("wrong_term", "that term")
            correct = term_fix.get("correct_term", "the correct term")
            return (
                f"Got it — I'll use '{correct}' instead of '{wrong}' going forward. "
                f"Thanks for the correction."
            )
        elif correction_type == "wrong_order":
            ordering = (correction.correction_data or {}).get("ordering_fix", {})
            first = ordering.get("component_should_be_first", "that")
            return (
                f"Understood — I'll prioritize checking the {first} first in future "
                f"troubleshooting. I've updated my diagnostic ordering."
            )
        elif correction_type == "missing_step":
            step = (correction.correction_data or {}).get("missing_step", "that step")
            return (
                f"Thanks for pointing that out. I'll include checking {step} "
                f"in future troubleshooting for this type of issue."
            )
        else:
            return (
                "Thanks for the correction — I've noted this feedback and will "
                "adjust my responses going forward."
            )

    async def save_correction(self, correction: FeedbackCorrection) -> None:
        """Persist correction to database."""
        if not self.db:
            logger.warning("CORRECTION | No database session, cannot save correction")
            return

        self.db.add(correction)
        await self.db.commit()
        logger.info(f"CORRECTION | Saved correction | type={correction.correction_type} | status={correction.status}")
