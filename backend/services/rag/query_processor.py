"""Query processing and enhancement for RAG."""

from dataclasses import dataclass
from typing import Any

from core.llm import LLMClient


@dataclass
class ProcessedQuery:
    """Processed and enhanced query."""

    original: str
    enhanced: str
    intent: str  # diagnose, repair, install, maintain, find_spec, understand_error, correction
    equipment_hints: dict[str, Any]
    urgency: str  # routine, urgent, safety


class QueryProcessor:
    """Process and enhance user queries for optimal retrieval.

    Extracts intent, equipment references, and urgency level.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def process(
        self,
        query: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> ProcessedQuery:
        """Analyze and enhance the user query.

        Args:
            query: Raw user query
            conversation_history: Previous messages for context

        Returns:
            ProcessedQuery with extracted metadata
        """
        # Use Claude to understand the query
        history_context = ""
        if conversation_history:
            recent = conversation_history[-3:]
            history_context = "\n".join(
                f"{m['role']}: {m['content'][:200]}" for m in recent
            )

        analysis_prompt = f"""Analyze this HVAC technician query:

Query: "{query}"

Previous conversation context: {history_context or "None"}

Extract:
1. PRIMARY_INTENT: What is the technician trying to do? (diagnose, repair, install, maintain, find_spec, understand_error, correction)
2. EQUIPMENT_TYPE: What type of equipment? (air_conditioner, heat_pump, furnace, boiler, mini_split, chiller, rooftop_unit, unknown)
3. BRAND_HINTS: Any brand names mentioned or implied?
4. MODEL_HINTS: Any model numbers or series mentioned?
5. SYMPTOMS: Key symptoms or issues described
6. COMPONENT_FOCUS: Specific components mentioned
7. URGENCY: Is this routine, urgent (customer waiting), or safety-related?
8. SEARCH_TERMS: Generate 3-5 alternative search phrases that would find relevant manual sections

Respond in JSON format."""

        analysis = await self.llm.analyze_json(prompt=analysis_prompt)

        # Build enhanced query for better retrieval
        enhanced_parts = [query]

        symptoms = analysis.get("SYMPTOMS", [])
        if isinstance(symptoms, list):
            enhanced_parts.extend(symptoms[:2])
        elif symptoms:
            enhanced_parts.append(str(symptoms))

        search_terms = analysis.get("SEARCH_TERMS", [])
        if isinstance(search_terms, list):
            enhanced_parts.extend(search_terms[:2])

        return ProcessedQuery(
            original=query,
            enhanced=" ".join(enhanced_parts),
            intent=analysis.get("PRIMARY_INTENT", "diagnose"),
            equipment_hints={
                "type": analysis.get("EQUIPMENT_TYPE"),
                "brand": analysis.get("BRAND_HINTS"),
                "model": analysis.get("MODEL_HINTS"),
                "component": analysis.get("COMPONENT_FOCUS"),
            },
            urgency=analysis.get("URGENCY", "routine"),
        )

    def quick_process(self, query: str) -> ProcessedQuery:
        """Quick processing without LLM call.

        Uses pattern matching for common query types.
        Useful for simple queries or when speed is critical.
        """
        query_lower = query.lower()

        # Detect intent from keywords
        intent = "diagnose"
        if any(phrase in query_lower for phrase in [
            "that's wrong", "that is wrong", "actually you should",
            "no, check", "wrong order", "we call that", "we say",
            "it's called", "not correct", "incorrect",
            "should be first", "should check first", "you got it backwards",
        ]):
            intent = "correction"
        elif any(kw in query_lower for kw in ["spec", "rating", "capacity", "tonnage", "seer"]):
            intent = "find_spec"
        elif any(kw in query_lower for kw in ["error", "code", "fault", "e", "f"]):
            intent = "understand_error"
        elif any(kw in query_lower for kw in ["install", "setup", "mount"]):
            intent = "install"
        elif any(kw in query_lower for kw in ["maintain", "service", "clean", "filter"]):
            intent = "maintain"

        # Detect urgency
        urgency = "routine"
        if any(kw in query_lower for kw in ["urgent", "emergency", "asap", "immediately"]):
            urgency = "urgent"
        elif any(kw in query_lower for kw in ["safety", "danger", "shock", "fire", "gas leak"]):
            urgency = "safety"

        return ProcessedQuery(
            original=query,
            enhanced=query,
            intent=intent,
            equipment_hints={},
            urgency=urgency,
        )
