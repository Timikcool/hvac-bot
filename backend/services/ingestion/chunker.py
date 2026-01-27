"""HVAC-aware document chunking."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config import get_settings


class ChunkType(Enum):
    """Types of content chunks."""

    TROUBLESHOOTING_STEP = "troubleshooting_step"
    SPECIFICATION = "specification"
    PROCEDURE = "procedure"
    SAFETY_WARNING = "safety_warning"
    ERROR_CODE = "error_code"
    WIRING_INFO = "wiring_info"
    GENERAL = "general"


@dataclass
class Chunk:
    """A chunk of content from a manual."""

    content: str
    chunk_type: ChunkType
    metadata: dict[str, Any]
    page_numbers: list[int] = field(default_factory=list)
    parent_section: str = ""
    has_image_reference: bool = False
    keywords: list[str] = field(default_factory=list)


class HVACChunker:
    """HVAC-aware document chunker that preserves semantic boundaries.

    Unlike generic chunkers, this understands HVAC document structure.
    """

    # Patterns that should never be split
    ATOMIC_PATTERNS = [
        r"(?:CAUTION|WARNING|DANGER):.*?(?=\n\n|\Z)",  # Safety warnings
        r"(?:Step \d+[.:]).*?(?=Step \d+|$)",  # Procedure steps
        r"(?:Error|Fault|Code)\s+[A-Z0-9]+:.*?(?=(?:Error|Fault|Code)\s+[A-Z0-9]+|$)",  # Error codes
    ]

    # HVAC-specific keywords for extraction
    HVAC_TERMS = [
        "compressor", "condenser", "evaporator", "refrigerant", "thermostat",
        "blower", "fan", "motor", "capacitor", "contactor", "relay",
        "pressure", "temperature", "superheat", "subcooling", "charge",
        "leak", "frozen", "icing", "short cycling", "not cooling", "not heating",
        "noise", "vibration", "tripping", "breaker", "fuse", "txv", "metering device",
    ]

    def __init__(
        self,
        max_chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        settings = get_settings()
        self.max_chunk_size = max_chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def chunk_document(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Create semantically meaningful chunks from document content.

        Preserves troubleshooting sequences, specifications, and procedures.

        Args:
            content: Full document text
            metadata: Document metadata (brand, model, etc.)

        Returns:
            List of Chunk objects
        """
        chunks = []

        # First pass: identify document sections
        sections = self._identify_sections(content)

        for section in sections:
            section_type = self._classify_section(section)

            if section_type == ChunkType.TROUBLESHOOTING_STEP:
                chunks.extend(self._chunk_troubleshooting(section, metadata))
            elif section_type == ChunkType.ERROR_CODE:
                chunks.extend(self._chunk_error_codes(section, metadata))
            elif section_type == ChunkType.SPECIFICATION:
                chunks.extend(self._chunk_specifications(section, metadata))
            elif section_type == ChunkType.SAFETY_WARNING:
                # Safety warnings are atomic - never split
                chunks.append(Chunk(
                    content=section["content"],
                    chunk_type=ChunkType.SAFETY_WARNING,
                    metadata={**metadata, "priority": "high"},
                    page_numbers=section.get("pages", []),
                    parent_section=section.get("title", ""),
                    has_image_reference=False,
                    keywords=self._extract_keywords(section["content"]),
                ))
            else:
                chunks.extend(self._chunk_generic(section, metadata))

        return chunks

    def _identify_sections(self, content: str) -> list[dict[str, Any]]:
        """Identify major sections in the document."""
        sections = []

        # Split by common section headers
        header_pattern = r"(?:^|\n)([A-Z][A-Z\s]{2,50})(?:\n|$)"
        parts = re.split(header_pattern, content)

        current_section = {"title": "Introduction", "content": "", "pages": [1]}

        for i, part in enumerate(parts):
            if i % 2 == 1:  # This is a header
                if current_section["content"].strip():
                    sections.append(current_section)
                current_section = {"title": part.strip(), "content": "", "pages": []}
            else:
                current_section["content"] += part

        if current_section["content"].strip():
            sections.append(current_section)

        return sections

    def _classify_section(self, section: dict[str, Any]) -> ChunkType:
        """Classify a section by its type."""
        title_lower = section.get("title", "").lower()
        content_lower = section.get("content", "").lower()

        if any(kw in title_lower for kw in ["troubleshoot", "diagnostic", "problem"]):
            return ChunkType.TROUBLESHOOTING_STEP

        if any(kw in title_lower for kw in ["error", "fault", "code"]):
            return ChunkType.ERROR_CODE

        if any(kw in title_lower for kw in ["spec", "rating", "capacity", "dimension"]):
            return ChunkType.SPECIFICATION

        if any(kw in title_lower for kw in ["safety", "warning", "caution", "danger"]):
            return ChunkType.SAFETY_WARNING

        if any(kw in title_lower for kw in ["wiring", "electrical", "schematic"]):
            return ChunkType.WIRING_INFO

        if any(kw in title_lower for kw in ["install", "procedure", "step", "maintenance"]):
            return ChunkType.PROCEDURE

        # Check content for patterns
        if "warning" in content_lower[:200] or "caution" in content_lower[:200]:
            return ChunkType.SAFETY_WARNING

        return ChunkType.GENERAL

    def _chunk_troubleshooting(
        self,
        section: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Special handling for troubleshooting sections.

        Keeps symptom -> cause -> solution sequences together.
        """
        chunks = []
        content = section["content"]

        # Pattern: "Problem: X ... Cause: Y ... Solution: Z"
        troubleshooting_pattern = (
            r"(?:Problem|Symptom|Issue)[:\s]+(.*?)"
            r"(?:Cause|Reason)[:\s]+(.*?)"
            r"(?:Solution|Fix|Action|Remedy)[:\s]+(.*?)"
            r"(?=(?:Problem|Symptom|Issue)[:\s]+|\Z)"
        )

        matches = list(re.finditer(troubleshooting_pattern, content, re.DOTALL | re.IGNORECASE))

        for match in matches:
            problem, cause, solution = match.groups()

            chunk_content = f"""PROBLEM: {problem.strip()}

CAUSE: {cause.strip()}

SOLUTION: {solution.strip()}"""

            chunks.append(Chunk(
                content=chunk_content,
                chunk_type=ChunkType.TROUBLESHOOTING_STEP,
                metadata={
                    **metadata,
                    "symptom_keywords": self._extract_keywords(problem),
                    "component_keywords": self._extract_component_names(cause + solution),
                },
                page_numbers=section.get("pages", []),
                parent_section=section.get("title", ""),
                has_image_reference="fig" in content.lower() or "diagram" in content.lower(),
                keywords=self._extract_keywords(chunk_content),
            ))

        # If no structured patterns found, fall back to generic chunking
        if not chunks:
            chunks = self._chunk_generic(section, metadata)
            for chunk in chunks:
                chunk.chunk_type = ChunkType.TROUBLESHOOTING_STEP

        return chunks

    def _chunk_error_codes(
        self,
        section: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Extract individual error codes as separate chunks."""
        chunks = []
        content = section["content"]

        # Common error code patterns
        error_pattern = (
            r"(?:Error|Fault|Code|E|F)\s*[-:]?\s*"
            r"([A-Z]?\d{1,3})[:\s]+"
            r"([^\n]+(?:\n(?![A-Z]?\d{1,3}[:\s]).*)*)"
        )

        for match in re.finditer(error_pattern, content):
            code, description = match.groups()

            chunks.append(Chunk(
                content=f"Error Code {code}: {description.strip()}",
                chunk_type=ChunkType.ERROR_CODE,
                metadata={
                    **metadata,
                    "error_code": code,
                    "searchable_code": f"E{code} F{code} error{code} fault{code}",
                },
                page_numbers=section.get("pages", []),
                parent_section="Error Codes",
                has_image_reference=False,
                keywords=[f"error {code}", f"fault {code}", f"code {code}"],
            ))

        return chunks

    def _chunk_specifications(
        self,
        section: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Keep specification tables together."""
        # For specifications, try to keep related data together
        content = section["content"]

        # If content is small enough, keep as single chunk
        if len(content) <= self.max_chunk_size:
            return [Chunk(
                content=content,
                chunk_type=ChunkType.SPECIFICATION,
                metadata=metadata,
                page_numbers=section.get("pages", []),
                parent_section=section.get("title", ""),
                has_image_reference=False,
                keywords=self._extract_keywords(content),
            )]

        # Otherwise, use generic chunking but mark as specification
        chunks = self._chunk_generic(section, metadata)
        for chunk in chunks:
            chunk.chunk_type = ChunkType.SPECIFICATION
        return chunks

    def _chunk_generic(
        self,
        section: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Generic chunking with overlap for general content."""
        chunks = []
        content = section["content"]

        # Split into paragraphs first
        paragraphs = re.split(r"\n\n+", content)

        current_chunk = ""
        current_length = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_length = len(para)

            if current_length + para_length > self.max_chunk_size:
                # Save current chunk
                if current_chunk:
                    chunks.append(Chunk(
                        content=current_chunk.strip(),
                        chunk_type=ChunkType.GENERAL,
                        metadata=metadata,
                        page_numbers=section.get("pages", []),
                        parent_section=section.get("title", ""),
                        has_image_reference="fig" in current_chunk.lower(),
                        keywords=self._extract_keywords(current_chunk),
                    ))

                # Start new chunk with overlap
                if self.chunk_overlap > 0 and current_chunk:
                    overlap_text = current_chunk[-self.chunk_overlap:]
                    current_chunk = overlap_text + "\n\n" + para
                    current_length = len(current_chunk)
                else:
                    current_chunk = para
                    current_length = para_length
            else:
                current_chunk += "\n\n" + para if current_chunk else para
                current_length += para_length + 2

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(Chunk(
                content=current_chunk.strip(),
                chunk_type=ChunkType.GENERAL,
                metadata=metadata,
                page_numbers=section.get("pages", []),
                parent_section=section.get("title", ""),
                has_image_reference="fig" in current_chunk.lower(),
                keywords=self._extract_keywords(current_chunk),
            ))

        return chunks

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract HVAC-relevant keywords for enhanced retrieval."""
        text_lower = text.lower()
        return [term for term in self.HVAC_TERMS if term in text_lower]

    def _extract_component_names(self, text: str) -> list[str]:
        """Extract component names from text."""
        components = []
        text_lower = text.lower()

        # Common HVAC components
        component_patterns = [
            "compressor", "condenser coil", "evaporator coil", "blower motor",
            "fan motor", "capacitor", "contactor", "relay", "transformer",
            "control board", "thermostat", "expansion valve", "txv",
            "reversing valve", "accumulator", "filter drier", "sight glass",
        ]

        for component in component_patterns:
            if component in text_lower:
                components.append(component)

        return components
