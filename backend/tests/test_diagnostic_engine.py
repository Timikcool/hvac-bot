"""Tests for diagnostic engine."""

import pytest
from types import SimpleNamespace

from services.rag.diagnostic_engine import DiagnosticEngine


class TestDiagnosticFormatting:
    """Test diagnostic flowchart formatting for LLM prompts."""

    def _make_flowchart(self):
        """Create a test flowchart with steps using SimpleNamespace."""
        step1 = SimpleNamespace(
            id="step-1",
            priority_weight=90,
            check_description="Check capacitor with multimeter",
            expected_result="Within 5% of rated uF",
            if_fail_action="Replace capacitor",
            if_pass_action="Check contactor",
            component="capacitor",
            tools_needed="Multimeter",
            safety_warning="Discharge capacitor before testing",
            is_active=True,
        )

        step2 = SimpleNamespace(
            id="step-2",
            priority_weight=75,
            check_description="Check contactor for pitting",
            expected_result="Clean contacts, no pitting",
            if_fail_action="Replace contactor",
            if_pass_action="Check wiring",
            component="contactor",
            tools_needed="Visual inspection",
            safety_warning=None,
            is_active=True,
        )

        step3 = SimpleNamespace(
            id="step-3",
            priority_weight=30,
            check_description="Check wiring connections",
            expected_result="Tight connections, no corrosion",
            if_fail_action="Repair wiring",
            if_pass_action=None,
            component="wiring",
            tools_needed="Multimeter",
            safety_warning="Ensure power is disconnected",
            is_active=True,
        )

        flowchart = SimpleNamespace(
            id="test-fc-1",
            symptom="compressor not starting",
            equipment_brand="Carrier",
            equipment_model=None,
            system_type="split",
            category="cooling",
            is_active=True,
            usage_count=10,
            success_rate=0.85,
            steps=[step1, step2, step3],
        )
        return flowchart

    def test_format_for_prompt(self):
        """Test that flowchart is formatted correctly for LLM prompt."""
        engine = DiagnosticEngine.__new__(DiagnosticEngine)
        flowchart = self._make_flowchart()

        result = engine.format_for_prompt(flowchart)

        # Should contain section header
        assert "DIAGNOSTIC FLOWCHART" in result
        assert "compressor not starting" in result

        # Should list steps in priority order
        cap_pos = result.find("capacitor")
        contactor_pos = result.find("contactor")
        wiring_pos = result.find("wiring")

        assert cap_pos < contactor_pos < wiring_pos, (
            "Steps should be ordered by priority (capacitor > contactor > wiring)"
        )

        # Should include safety warning
        assert "Discharge capacitor" in result

    def test_get_step_components(self):
        """Test extracting ordered component list."""
        engine = DiagnosticEngine.__new__(DiagnosticEngine)
        flowchart = self._make_flowchart()

        components = engine.get_step_components(flowchart)

        assert components == ["capacitor", "contactor", "wiring"]

    def test_get_step_components_empty(self):
        """Test with flowchart that has no steps."""
        engine = DiagnosticEngine.__new__(DiagnosticEngine)
        flowchart = self._make_flowchart()
        flowchart.steps = []

        components = engine.get_step_components(flowchart)
        assert components == []


class TestDiagnosticReranking:
    """Test that retriever diagnostic re-ranking works correctly."""

    def test_apply_diagnostic_ranking_boosts_top_component(self):
        """Chunks about the highest-priority component should rank first."""
        from services.rag.retriever import HVACRetriever

        retriever = HVACRetriever.__new__(HVACRetriever)

        chunks = [
            {"content": "Check wiring connections for corrosion", "score": 0.85, "metadata": {"component": "wiring"}},
            {"content": "Capacitor failure is the most common cause", "score": 0.80, "metadata": {"component": "capacitor"}},
            {"content": "Contactor may have pitted contacts", "score": 0.82, "metadata": {"component": "contactor"}},
        ]

        diagnostic_components = ["capacitor", "contactor", "wiring"]

        result = retriever.apply_diagnostic_ranking(chunks, diagnostic_components)

        # Capacitor chunk should now be first (boosted from 0.80)
        assert "capacitor" in result[0]["content"].lower()

    def test_apply_diagnostic_ranking_empty_components(self):
        """Should return chunks unchanged when no diagnostic components."""
        from services.rag.retriever import HVACRetriever

        retriever = HVACRetriever.__new__(HVACRetriever)

        chunks = [
            {"content": "Some content", "score": 0.85, "metadata": {}},
        ]

        result = retriever.apply_diagnostic_ranking(chunks, [])
        assert result == chunks

    def test_apply_diagnostic_ranking_empty_chunks(self):
        """Should return empty list for empty chunks."""
        from services.rag.retriever import HVACRetriever

        retriever = HVACRetriever.__new__(HVACRetriever)

        result = retriever.apply_diagnostic_ranking([], ["capacitor"])
        assert result == []
