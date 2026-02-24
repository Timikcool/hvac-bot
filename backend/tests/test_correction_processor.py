"""Tests for correction detection and processing."""

import pytest

from services.improvement.correction_processor import CorrectionProcessor


@pytest.fixture
def processor():
    """Create a CorrectionProcessor without LLM client."""
    return CorrectionProcessor(llm_client=None, db_session=None)


class TestCorrectionDetection:
    """Test that corrections are properly detected from user messages."""

    def test_detect_thats_wrong(self, processor):
        assert processor.detect_correction("That's wrong, check the capacitor first")

    def test_detect_actually(self, processor):
        assert processor.detect_correction("Actually you should check the contactor first")

    def test_detect_wrong_order(self, processor):
        assert processor.detect_correction("The order is wrong, capacitor should be first")

    def test_detect_we_call_that(self, processor):
        assert processor.detect_correction("We call that a contactor, not relay contacts")

    def test_detect_no_prefix(self, processor):
        assert processor.detect_correction("No, check the capacitor first")

    def test_detect_should_be_first(self, processor):
        assert processor.detect_correction("Capacitor should be checked first")

    def test_detect_got_backwards(self, processor):
        assert processor.detect_correction("You got it backwards, the cap is the first thing to check")

    def test_detect_its_called(self, processor):
        assert processor.detect_correction("It's called a contactor in the field")

    def test_not_detect_normal_question(self, processor):
        assert not processor.detect_correction("What is the superheat for this unit?")

    def test_not_detect_normal_statement(self, processor):
        assert not processor.detect_correction("The compressor is making a clicking noise")

    def test_not_detect_thanks(self, processor):
        assert not processor.detect_correction("Thanks, that was helpful!")


class TestCorrectionAcknowledgment:
    """Test acknowledgment message generation."""

    def test_terminology_acknowledgment(self, processor):
        from models.diagnostic import FeedbackCorrection

        correction = FeedbackCorrection(
            correction_type="wrong_terminology",
            correction_data={
                "terminology_fix": {
                    "wrong_term": "relay contacts",
                    "correct_term": "contactor",
                }
            },
        )
        ack = processor.generate_acknowledgment(correction)
        assert "contactor" in ack
        assert "relay contacts" in ack

    def test_ordering_acknowledgment(self, processor):
        from models.diagnostic import FeedbackCorrection

        correction = FeedbackCorrection(
            correction_type="wrong_order",
            correction_data={
                "ordering_fix": {
                    "component_should_be_first": "capacitor",
                }
            },
        )
        ack = processor.generate_acknowledgment(correction)
        assert "capacitor" in ack
        assert "first" in ack

    def test_missing_step_acknowledgment(self, processor):
        from models.diagnostic import FeedbackCorrection

        correction = FeedbackCorrection(
            correction_type="missing_step",
            correction_data={
                "missing_step": "check the disconnect switch",
            },
        )
        ack = processor.generate_acknowledgment(correction)
        assert "check the disconnect switch" in ack

    def test_generic_acknowledgment(self, processor):
        from models.diagnostic import FeedbackCorrection

        correction = FeedbackCorrection(
            correction_type="other",
            correction_data={},
        )
        ack = processor.generate_acknowledgment(correction)
        assert "correction" in ack.lower() or "feedback" in ack.lower()
