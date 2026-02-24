"""Tests for terminology mapping system."""

import pytest

from services.rag.terminology import TerminologyMapper


@pytest.fixture
def mapper():
    """Create a TerminologyMapper with seed data only (no DB)."""
    import asyncio

    tm = TerminologyMapper(db_session=None)
    # Load seed data via the async load method (no DB means only seeds)
    asyncio.get_event_loop().run_until_complete(tm.load())
    return tm


class TestTerminologyMapper:
    """Test terminology normalization and response post-processing."""

    def test_seed_data_loaded(self, mapper):
        """Seed mappings should be loaded on init."""
        assert len(mapper._mappings) > 0
        assert "relay contacts" in mapper._mappings
        assert mapper._mappings["relay contacts"] == "contactor"

    def test_get_field_term(self, mapper):
        """Should return field term for known textbook term."""
        assert mapper.get_field_term("relay contacts") == "contactor"
        assert mapper.get_field_term("thermostatic expansion valve") == "TXV"
        assert mapper.get_field_term("thermal overload relay") == "OL"

    def test_get_field_term_unknown(self, mapper):
        """Should return None for unknown terms."""
        assert mapper.get_field_term("quantum flux capacitor") is None

    def test_apply_to_response(self, mapper):
        """Should replace textbook terms with field terms in response."""
        text = "Check the relay contacts and the thermostatic expansion valve."
        result = mapper.apply_to_response(text)
        assert "contactor" in result
        assert "TXV" in result
        assert "relay contacts" not in result

    def test_apply_to_response_case_insensitive(self, mapper):
        """Should handle case-insensitive matching."""
        text = "The Thermal Overload Relay is tripping."
        result = mapper.apply_to_response(text)
        assert "OL" in result

    def test_apply_to_response_no_partial_match(self, mapper):
        """Should not replace partial matches within words."""
        text = "The contactor is fine."  # 'contactor' is already a field term
        result = mapper.apply_to_response(text)
        assert result == text  # No change

    def test_apply_to_query(self, mapper):
        """Should expand query with textbook variants when field terms are used."""
        query = "how to check the contactor"
        result = mapper.apply_to_query(query)
        # Should contain original AND textbook variant
        assert "contactor" in result
        assert "relay contacts" in result or "magnetic relay" in result

    def test_apply_to_query_no_expansion_needed(self, mapper):
        """Should return original query if no terms to expand."""
        query = "how to clean the filter"
        result = mapper.apply_to_query(query)
        assert result == query

    def test_get_corrections_summary(self, mapper):
        """Should identify textbook terms in text and return corrections."""
        text = "Replace the relay contacts and check the run capacitor."
        corrections = mapper.get_corrections_summary(text)
        assert "relay contacts" in corrections
        assert corrections["relay contacts"] == "contactor"

    def test_multiple_replacements(self, mapper):
        """Should handle multiple replacements in same text."""
        text = (
            "Check the relay contacts, then inspect the thermostatic expansion valve "
            "and measure the temperature differential."
        )
        result = mapper.apply_to_response(text)
        assert "contactor" in result
        assert "TXV" in result
        assert "delta T" in result


class TestTerminologyMapperEdgeCases:
    """Test edge cases in terminology mapping."""

    def test_empty_text(self, mapper):
        result = mapper.apply_to_response("")
        assert result == ""

    def test_none_term_lookup(self, mapper):
        assert mapper.get_field_term("") is None

    def test_apply_to_query_empty(self, mapper):
        result = mapper.apply_to_query("")
        assert result == ""
