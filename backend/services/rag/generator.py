"""Grounded response generation for HVAC queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from core.guardrails import ConfidenceLevel
from core.llm import LLMClient
from core.logging import get_logger

if TYPE_CHECKING:
    from services.rag.terminology import TerminologyMapper

logger = get_logger("rag.generator")


@dataclass
class GeneratedResponse:
    """Response from the generator."""

    answer: str
    confidence: ConfidenceLevel
    citations: list[dict[str, Any]] = field(default_factory=list)
    safety_warnings: list[str] = field(default_factory=list)
    suggested_followups: list[str] = field(default_factory=list)
    requires_escalation: bool = False


class GroundedGenerator:
    """Generate responses strictly grounded in retrieved manual content.

    Implements multiple guardrails against hallucination.
    """

    SYSTEM_PROMPT = """You are an HVAC technical assistant helping field technicians.
Your responses must be STRICTLY based on the provided manual excerpts.

CRITICAL RULES:
1. ONLY answer based on information in the provided sources
2. If the sources don't contain the answer, say "I don't have this information in the available manuals"
3. NEVER make up specifications, procedures, or troubleshooting steps
4. ALWAYS cite your sources using [Source X] notation
5. If sources are ambiguous or contradictory, note this explicitly
6. Prioritize safety - always include relevant warnings from the manuals
7. Be concise - technicians need quick answers in the field

TROUBLESHOOTING FORMAT (when diagnosing issues):
- Present diagnostic checks ordered by PROBABILITY (most likely cause FIRST)
- Format: "1. Check [X] first (most common cause)... 2. If not, check [Y]..."
- Follow diagnostic flowchart logic, NOT alphabetical or textbook order
- Each check should include: what to check, what you expect to find, what it means
- If a DIAGNOSTIC FLOWCHART is provided below, use its ordering as your guide

FIELD TERMINOLOGY:
- Use field-standard terms, not textbook language
- Say "contactor" not "relay contacts"
- Say "TXV" not "thermostatic expansion valve"
- Say "cap" or "capacitor" not "run capacitor"
- Say "OL" or "overload" not "thermal overload relay"
- Say "delta T" not "temperature differential"
- Say "amp draw" not "ampere draw"

RESPONSE FORMAT:
- Start with direct answer to the question
- Include step-by-step instructions if applicable
- Cite sources for each claim: [Source 1], [Source 2]
- Add safety warnings if relevant (from manuals)
- Keep it practical and actionable"""

    def __init__(
        self,
        llm_client: LLMClient,
        terminology_mapper: Optional[TerminologyMapper] = None,
    ):
        self.llm = llm_client
        self.terminology = terminology_mapper

    async def generate(
        self,
        query: str,
        retrieved_chunks: list[dict[str, Any]],
        equipment_context: dict[str, Any],
        conversation_history: list[dict[str, Any]] | None = None,
        diagnostic_context: str | None = None,
    ) -> GeneratedResponse:
        """Generate a grounded response with citations.

        Args:
            query: User query
            retrieved_chunks: Retrieved source chunks
            equipment_context: Equipment brand/model context
            conversation_history: Previous messages
            diagnostic_context: Formatted diagnostic flowchart text (from DiagnosticEngine)

        Returns:
            GeneratedResponse with answer and metadata
        """
        logger.info(f"GENERATOR | Generating response | chunks={len(retrieved_chunks)} | query={query[:60]}...")
        logger.debug(f"GENERATOR | Equipment: {equipment_context}")
        if diagnostic_context:
            logger.info("GENERATOR | Diagnostic flowchart context provided")

        # Check if we have sufficient information
        if not retrieved_chunks or all(c["score"] < 0.5 for c in retrieved_chunks):
            logger.warning("GENERATOR | Insufficient information - no quality chunks available")
            return self._generate_insufficient_info_response(query, equipment_context)

        # Format retrieved chunks with source identifiers
        formatted_sources = self._format_sources(retrieved_chunks)
        logger.debug(f"GENERATOR | Formatted {len(retrieved_chunks)} sources | total_chars={len(formatted_sources)}")

        # Build user prompt with optional diagnostic context
        diagnostic_section = ""
        if diagnostic_context:
            diagnostic_section = f"""
{diagnostic_context}

IMPORTANT: Use the diagnostic flowchart above to ORDER your troubleshooting steps.
Present the highest-priority checks FIRST. The flowchart reflects real-world failure
probabilities from experienced technicians.

"""

        user_prompt = f"""EQUIPMENT CONTEXT:
- Brand: {equipment_context.get('brand', 'Unknown')}
- Model: {equipment_context.get('model', 'Unknown')}
- System Type: {equipment_context.get('system_type', 'Unknown')}
{diagnostic_section}
AVAILABLE SOURCES:
{formatted_sources}

TECHNICIAN'S QUESTION:
{query}

Remember: Only answer based on the sources above. Cite each source used.
Order troubleshooting steps by probability (most likely cause first)."""

        # Build messages with history
        messages = []
        if conversation_history:
            for msg in conversation_history[-6:]:  # Keep last 6 messages
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })
        messages.append({"role": "user", "content": user_prompt})

        logger.debug("GENERATOR | Calling LLM...")
        response = await self.llm.generate(
            prompt="",  # Using messages instead
            system=self.SYSTEM_PROMPT,
            messages=messages,
            temperature=0.1,  # Low temperature for factual responses
        )

        answer = response.content
        logger.debug(f"GENERATOR | LLM response received | length={len(answer)} chars")

        # Apply terminology corrections (textbook → field terms)
        terminology_corrections = {}
        if self.terminology:
            terminology_corrections = self.terminology.get_corrections_summary(answer)
            answer = self.terminology.apply_to_response(answer)
            if terminology_corrections:
                logger.info(
                    f"GENERATOR | Applied {len(terminology_corrections)} terminology corrections"
                )

        # Post-process response
        citations = self._extract_citations(answer, retrieved_chunks)
        safety_warnings = self._extract_safety_warnings(retrieved_chunks)
        confidence = self._assess_confidence(answer, retrieved_chunks)

        logger.info(
            f"GENERATOR | Response complete | confidence={confidence.value} | "
            f"citations={len(citations)} | safety_warnings={len(safety_warnings)}"
        )

        return GeneratedResponse(
            answer=answer,
            confidence=confidence,
            citations=citations,
            safety_warnings=safety_warnings,
            suggested_followups=self._generate_followups(query, answer),
            requires_escalation=confidence == ConfidenceLevel.LOW,
        )

    def _format_sources(self, chunks: list[dict[str, Any]]) -> str:
        """Format retrieved chunks as numbered sources."""
        formatted = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.get("metadata", {})
            source_header = f"[Source {i}] {meta.get('manual_title', 'Manual')}"
            if meta.get("page_numbers"):
                pages = meta["page_numbers"]
                if isinstance(pages, list) and pages:
                    source_header += f", Page(s) {', '.join(map(str, pages))}"
            if meta.get("parent_section"):
                source_header += f", Section: {meta['parent_section']}"

            formatted.append(f"{source_header}\n{chunk['content']}\n")

        return "\n---\n".join(formatted)

    def _assess_confidence(
        self,
        answer: str,
        chunks: list[dict[str, Any]],
    ) -> ConfidenceLevel:
        """Assess confidence based on retrieval scores and answer content."""
        # Check for uncertainty phrases
        uncertainty_phrases = [
            "don't have this information",
            "not found in",
            "no specific information",
            "cannot confirm",
            "may need to consult",
        ]

        if any(phrase in answer.lower() for phrase in uncertainty_phrases):
            return ConfidenceLevel.LOW

        # Check retrieval scores
        scores = [c["score"] for c in chunks if c.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0

        if avg_score > 0.8:
            return ConfidenceLevel.HIGH
        elif avg_score > 0.65:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    def _extract_citations(
        self,
        answer: str,
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract and validate citations from the answer."""
        import re

        citations = []
        seen_sources = set()
        
        # Find ALL "Source N" patterns anywhere in the text
        # This handles [Source 1], [Source 1, Source 2], Source 1, etc.
        source_pattern = r"Source (\d+)"

        for match in re.finditer(source_pattern, answer):
            source_num = int(match.group(1)) - 1
            
            # Skip duplicates
            if source_num in seen_sources:
                continue
            seen_sources.add(source_num)
            
            if 0 <= source_num < len(chunks):
                chunk = chunks[source_num]
                meta = chunk.get("metadata", {})
                citations.append({
                    "source_number": source_num + 1,
                    "title": meta.get("title") or meta.get("manual_title") or "Unknown",
                    "page": meta.get("page_numbers"),
                    "section": meta.get("parent_section"),
                    "document_id": meta.get("document_id") or meta.get("manual_id"),
                    "document_type": meta.get("document_type", "manual"),
                })
            else:
                # Source referenced but not in chunks - still add it
                logger.warning(f"GENERATOR | Source {source_num + 1} referenced but only {len(chunks)} chunks available")
                citations.append({
                    "source_number": source_num + 1,
                    "title": "Unknown Source",
                    "page": None,
                    "section": None,
                    "document_id": None,
                    "document_type": "unknown",
                })
        
        # Sort by source number
        citations.sort(key=lambda c: c["source_number"])

        return citations

    def _extract_safety_warnings(
        self,
        chunks: list[dict[str, Any]],
    ) -> list[str]:
        """Extract safety-relevant information from sources."""
        import re

        warnings = []

        for chunk in chunks:
            content = chunk.get("content", "")
            meta = chunk.get("metadata", {})

            if meta.get("chunk_type") == "safety_warning":
                warnings.append(content[:500])
            elif any(term in content.lower() for term in ["warning", "caution", "danger"]):
                # Extract warning sentences
                warning_pattern = r"(?:WARNING|CAUTION|DANGER)[:\s]+([^.!]+[.!])"
                matches = re.findall(warning_pattern, content, re.IGNORECASE)
                warnings.extend(matches[:2])  # Limit per chunk

        # Deduplicate
        return list(set(warnings))[:5]

    def _generate_followups(self, query: str, answer: str) -> list[str]:
        """Generate relevant follow-up questions."""
        followups = []
        query_lower = query.lower()
        answer_lower = answer.lower()

        if "compressor" in query_lower or "compressor" in answer_lower:
            followups.append("What are the compressor amp draw specifications?")
        if "refrigerant" in query_lower or "refrigerant" in answer_lower:
            followups.append("What is the factory refrigerant charge for this unit?")
        if "error" in query_lower or "code" in query_lower:
            followups.append("How do I clear/reset this error code?")
        if "not cooling" in query_lower or "not heating" in query_lower:
            followups.append("What are the normal operating pressures?")

        return followups[:3]

    def _generate_insufficient_info_response(
        self,
        query: str,
        equipment: dict[str, Any],
    ) -> GeneratedResponse:
        """Generate response when no relevant information is found."""
        brand = equipment.get("brand", "this equipment")
        model = equipment.get("model", "")

        return GeneratedResponse(
            answer=f"""I don't have specific information about this in the available manuals for {brand} {model}.

This could mean:
1. The manual for this specific model hasn't been uploaded yet
2. This issue isn't covered in the service manual
3. You may need the installation guide or parts manual instead

Suggested actions:
- Check if you have the correct model selected
- Try rephrasing your question with different terms
- Consult the physical manual or contact technical support""",
            confidence=ConfidenceLevel.NONE,
            citations=[],
            safety_warnings=[],
            suggested_followups=[
                "Do you want me to search across all brands?",
                "Can you provide more details about the symptom?",
                "Would you like to try a different model number?",
            ],
            requires_escalation=True,
        )
