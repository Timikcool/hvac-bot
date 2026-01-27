"""Text processing utilities for HVAC content."""

import re
import unicodedata
from typing import Any


def normalize_text(text: str) -> str:
    """Normalize text for consistent processing.

    - Unicode normalization (NFC)
    - Whitespace normalization
    - Remove control characters
    """
    # Unicode normalization
    text = unicodedata.normalize("NFC", text)

    # Remove control characters except newlines and tabs
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Cc" or char in "\n\t"
    )

    # Normalize whitespace (multiple spaces to single)
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize newlines (multiple to double)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def clean_extracted_text(text: str) -> str:
    """Clean text extracted from PDFs.

    Handles common PDF extraction issues:
    - Hyphenated line breaks
    - Header/footer artifacts
    - Page numbers
    """
    # Fix hyphenated words at line breaks
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)

    # Remove standalone page numbers
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    # Remove common header/footer patterns
    text = re.sub(r"Page \d+ of \d+", "", text, flags=re.IGNORECASE)

    return normalize_text(text)


def extract_model_numbers(text: str) -> list[str]:
    """Extract potential HVAC model numbers from text.

    Common patterns:
    - Letter + numbers: A1234BC
    - Dash-separated: XYZ-123-456
    - Underscore-separated: MODEL_123_V2
    """
    patterns = [
        r"\b[A-Z]{1,4}[-]?\d{2,6}[-]?[A-Z]{0,4}\d{0,4}\b",  # Carrier, Lennox style
        r"\b\d{3,5}[-][A-Z]{1,3}[-]?\d{2,4}\b",  # Trane style
        r"\b[A-Z]{2,4}\d{4,8}[A-Z]?\b",  # General pattern
    ]

    matches = set()
    for pattern in patterns:
        found = re.findall(pattern, text, re.IGNORECASE)
        matches.update(m.upper() for m in found)

    return list(matches)


def extract_error_codes(text: str) -> list[dict[str, str]]:
    """Extract error/fault codes from text.

    Returns list of dicts with 'code' and 'context' keys.
    """
    patterns = [
        # E01, F02, etc.
        r"(?:Error|Fault|Code|E|F)\s*[-:]?\s*(\d{1,3})\s*[-:]\s*([^\n.]{10,100})",
        # Error E01: description
        r"(?:Error|Fault)\s+([A-Z]?\d{1,3})\s*[-:]\s*([^\n.]{10,100})",
    ]

    results = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            code = match.group(1).strip()
            context = match.group(2).strip() if len(match.groups()) > 1 else ""
            results.append({"code": code, "context": context})

    return results


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to max length, preserving word boundaries."""
    if len(text) <= max_length:
        return text

    # Find last space before max_length
    truncate_at = text.rfind(" ", 0, max_length - len(suffix))
    if truncate_at == -1:
        truncate_at = max_length - len(suffix)

    return text[:truncate_at] + suffix


def count_tokens_estimate(text: str) -> int:
    """Rough estimate of token count (for Claude models).

    Approximation: ~4 characters per token for English text.
    """
    return len(text) // 4


def extract_section_headers(text: str) -> list[str]:
    """Extract section headers from document text."""
    # Common header patterns in technical documents
    patterns = [
        r"^([A-Z][A-Z\s]{2,50})$",  # ALL CAPS lines
        r"^\d+\.\s+([A-Z][A-Za-z\s]{5,50})$",  # Numbered sections
        r"^(?:Chapter|Section|Part)\s+\d+[.:]\s*(.+)$",  # Chapter/Section headers
    ]

    headers = []
    for line in text.split("\n"):
        line = line.strip()
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                header = match.group(1) if match.groups() else line
                if len(header) > 3:  # Filter out very short matches
                    headers.append(header.strip())
                break

    return headers


def format_citations(sources: list[dict[str, Any]]) -> str:
    """Format source citations for display.

    Args:
        sources: List of source dicts with 'title', 'page', etc.

    Returns:
        Formatted citation string
    """
    if not sources:
        return ""

    citations = []
    for i, source in enumerate(sources, 1):
        parts = []
        if source.get("title"):
            parts.append(source["title"])
        if source.get("brand"):
            parts.append(f"({source['brand']})")
        if source.get("page"):
            parts.append(f"p.{source['page']}")

        citations.append(f"[{i}] {' '.join(parts)}")

    return "\n".join(citations)


def highlight_keywords(text: str, keywords: list[str]) -> str:
    """Add markdown highlighting to keywords in text.

    Returns text with **keyword** formatting for matches.
    """
    for keyword in keywords:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        text = pattern.sub(f"**{keyword}**", text)

    return text


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Simple sentence splitting (handles common abbreviations)
    abbreviations = r"(?<!\b(?:Mr|Mrs|Dr|Jr|Sr|vs|etc|e\.g|i\.e))"
    pattern = abbreviations + r"[.!?]+\s+"

    sentences = re.split(pattern, text)
    return [s.strip() for s in sentences if s.strip()]
