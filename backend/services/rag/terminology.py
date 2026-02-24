"""HVAC field terminology mapper.

Converts textbook/manual language to field-standard HVAC terminology.
Learns from technician corrections over time.
"""

import re
from typing import Any, Optional

from core.logging import get_logger
from models.diagnostic import TerminologyMapping

logger = get_logger("rag.terminology")


# Initial seed mappings: textbook_term -> field_term
# These are loaded at startup and augmented from the database.
SEED_MAPPINGS: list[dict[str, str]] = [
    # Electrical components
    {"textbook": "relay contacts", "field": "contactor", "context": "electrical"},
    {"textbook": "magnetic relay", "field": "contactor", "context": "electrical"},
    {"textbook": "thermal overload relay", "field": "OL", "context": "electrical"},
    {"textbook": "thermal overload", "field": "overload", "context": "electrical"},
    {"textbook": "run capacitor", "field": "cap", "context": "electrical"},
    {"textbook": "start capacitor", "field": "start cap", "context": "electrical"},
    {"textbook": "dual run capacitor", "field": "dual cap", "context": "electrical"},
    {"textbook": "compressor contactor", "field": "contactor", "context": "electrical"},
    {"textbook": "disconnect switch", "field": "disconnect", "context": "electrical"},
    {"textbook": "circuit breaker", "field": "breaker", "context": "electrical"},
    {"textbook": "high-pressure switch", "field": "high-pressure cutout", "context": "electrical"},
    {"textbook": "low-pressure switch", "field": "low-pressure cutout", "context": "electrical"},
    # Refrigerant system
    {"textbook": "thermostatic expansion valve", "field": "TXV", "context": "refrigerant"},
    {"textbook": "expansion valve", "field": "TXV", "context": "refrigerant"},
    {"textbook": "metering device", "field": "TXV", "context": "refrigerant"},
    {"textbook": "fixed orifice metering device", "field": "piston", "context": "refrigerant"},
    {"textbook": "refrigerant charge amount", "field": "charge", "context": "refrigerant"},
    {"textbook": "superheat measurement", "field": "superheat reading", "context": "refrigerant"},
    {"textbook": "subcooling measurement", "field": "subcooling reading", "context": "refrigerant"},
    {"textbook": "suction line", "field": "suction line", "context": "refrigerant"},
    {"textbook": "liquid line", "field": "liquid line", "context": "refrigerant"},
    {"textbook": "filter drier", "field": "filter drier", "context": "refrigerant"},
    {"textbook": "accumulator", "field": "accumulator", "context": "refrigerant"},
    {"textbook": "reversing valve", "field": "reversing valve", "context": "refrigerant"},
    # Major components
    {"textbook": "evaporator coil", "field": "evaporator", "context": "components"},
    {"textbook": "condenser coil", "field": "condenser", "context": "components"},
    {"textbook": "blower motor", "field": "blower motor", "context": "components"},
    {"textbook": "condenser fan motor", "field": "fan motor", "context": "components"},
    {"textbook": "indoor blower assembly", "field": "blower", "context": "components"},
    {"textbook": "air handling unit", "field": "air handler", "context": "components"},
    {"textbook": "condensing unit", "field": "condenser", "context": "components"},
    # Measurements & readings
    {"textbook": "ampere draw", "field": "amp draw", "context": "measurements"},
    {"textbook": "locked rotor amperage", "field": "LRA", "context": "measurements"},
    {"textbook": "rated load amperage", "field": "RLA", "context": "measurements"},
    {"textbook": "full load amperage", "field": "FLA", "context": "measurements"},
    {"textbook": "static pressure measurement", "field": "static pressure", "context": "measurements"},
    {"textbook": "temperature differential", "field": "delta T", "context": "measurements"},
    # System types
    {"textbook": "split system air conditioner", "field": "split system", "context": "systems"},
    {"textbook": "packaged unit", "field": "package unit", "context": "systems"},
    {"textbook": "ductless mini-split", "field": "mini-split", "context": "systems"},
    {"textbook": "rooftop unit", "field": "RTU", "context": "systems"},
    {"textbook": "variable refrigerant flow", "field": "VRF", "context": "systems"},
]


class TerminologyMapper:
    """Maps textbook HVAC terms to field-standard terminology.

    Loads seed mappings at init, augments from database,
    and learns from technician corrections.
    """

    def __init__(self, db_session: Any = None):
        self.db = db_session
        self._mappings: dict[str, str] = {}  # textbook_lower -> field_term
        self._reverse: dict[str, list[str]] = {}  # field_lower -> [textbook_terms]
        self._loaded = False

    async def load(self) -> None:
        """Load terminology mappings from seed data and database."""
        # Load seed mappings
        for mapping in SEED_MAPPINGS:
            key = mapping["textbook"].lower()
            self._mappings[key] = mapping["field"]
            field_lower = mapping["field"].lower()
            if field_lower not in self._reverse:
                self._reverse[field_lower] = []
            self._reverse[field_lower].append(mapping["textbook"])

        # Load database mappings (override seeds if present)
        if self.db:
            try:
                from sqlalchemy import select

                result = await self.db.execute(
                    select(TerminologyMapping).where(
                        TerminologyMapping.is_active == True  # noqa: E712
                    )
                )
                db_mappings = result.scalars().all()
                for m in db_mappings:
                    key = m.textbook_term.lower()
                    self._mappings[key] = m.field_term
                    field_lower = m.field_term.lower()
                    if field_lower not in self._reverse:
                        self._reverse[field_lower] = []
                    if m.textbook_term not in self._reverse[field_lower]:
                        self._reverse[field_lower].append(m.textbook_term)
                logger.info(
                    f"TERMINOLOGY | Loaded {len(db_mappings)} mappings from database"
                )
            except Exception as e:
                logger.warning(f"TERMINOLOGY | Could not load from database: {e}")

        self._loaded = True
        logger.info(f"TERMINOLOGY | Total mappings loaded: {len(self._mappings)}")

    def get_field_term(self, textbook_term: str) -> Optional[str]:
        """Look up the field-standard term for a textbook term."""
        return self._mappings.get(textbook_term.lower())

    def apply_to_response(self, text: str) -> str:
        """Replace textbook terms with field terms in a generated response.

        Uses word-boundary-aware replacement to avoid partial matches.
        Longer terms are replaced first to prevent partial replacements.
        """
        if not self._loaded or not self._mappings:
            return text

        result = text
        corrections_applied = {}

        # Sort by length descending so longer phrases match first
        sorted_mappings = sorted(
            self._mappings.items(), key=lambda x: len(x[0]), reverse=True
        )

        for textbook_lower, field_term in sorted_mappings:
            # Case-insensitive word boundary replacement
            pattern = re.compile(
                r"\b" + re.escape(textbook_lower) + r"\b",
                re.IGNORECASE,
            )
            if pattern.search(result):
                result = pattern.sub(field_term, result)
                corrections_applied[textbook_lower] = field_term

        if corrections_applied:
            logger.debug(
                f"TERMINOLOGY | Applied {len(corrections_applied)} corrections: "
                f"{corrections_applied}"
            )

        return result

    def apply_to_query(self, query: str) -> str:
        """Expand query with field term variants for better retrieval.

        If the query uses a field term, also include the textbook variants
        so the vector search finds matches in manual text.
        """
        if not self._loaded:
            return query

        expanded_parts = [query]

        for field_lower, textbook_terms in self._reverse.items():
            if field_lower in query.lower():
                for tb_term in textbook_terms[:2]:  # Add up to 2 variants
                    if tb_term.lower() not in query.lower():
                        expanded_parts.append(tb_term)

        if len(expanded_parts) > 1:
            expanded = " ".join(expanded_parts)
            logger.debug(f"TERMINOLOGY | Query expanded: '{query}' → '{expanded}'")
            return expanded

        return query

    async def add_mapping(
        self,
        textbook_term: str,
        field_term: str,
        context: Optional[str] = None,
        source: str = "technician_correction",
    ) -> None:
        """Add a new terminology mapping (from correction or admin)."""
        key = textbook_term.lower()

        # Update in-memory
        self._mappings[key] = field_term
        field_lower = field_term.lower()
        if field_lower not in self._reverse:
            self._reverse[field_lower] = []
        if textbook_term not in self._reverse[field_lower]:
            self._reverse[field_lower].append(textbook_term)

        # Persist to database
        if self.db:
            try:
                from sqlalchemy import select

                # Check if mapping exists
                result = await self.db.execute(
                    select(TerminologyMapping).where(
                        TerminologyMapping.textbook_term == textbook_term
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.field_term = field_term
                    existing.confirmed_by_count += 1
                    existing.source = source
                else:
                    new_mapping = TerminologyMapping(
                        textbook_term=textbook_term,
                        field_term=field_term,
                        context=context,
                        source=source,
                        confirmed_by_count=1,
                    )
                    self.db.add(new_mapping)

                await self.db.commit()
                logger.info(
                    f"TERMINOLOGY | Added mapping: '{textbook_term}' → '{field_term}'"
                )
            except Exception as e:
                logger.error(f"TERMINOLOGY | Failed to persist mapping: {e}")

    def get_all_mappings(self) -> dict[str, str]:
        """Return all current mappings."""
        return dict(self._mappings)

    def get_corrections_summary(self, text: str) -> dict[str, str]:
        """Return which corrections would be applied to a text, without applying."""
        corrections = {}
        for textbook_lower, field_term in self._mappings.items():
            pattern = re.compile(
                r"\b" + re.escape(textbook_lower) + r"\b", re.IGNORECASE
            )
            if pattern.search(text):
                corrections[textbook_lower] = field_term
        return corrections
