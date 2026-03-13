from __future__ import annotations

import pytest

from voxagent.agent.handoff import HandoffDetector, HandoffReason, events_to_transcript
from voxagent.models import ConversationEvent


class TestHandoffDetector:
    def test_no_handoff_on_normal_conversation(self) -> None:
        detector = HandoffDetector()
        transcript = [
            {"role": "user", "content": "What are your business hours?"},
            {"role": "assistant", "content": "We are open 9am to 5pm."},
            {"role": "user", "content": "Thank you!"},
        ]
        assert detector.check(transcript) is None

    def test_explicit_request_detected(self) -> None:
        detector = HandoffDetector()
        transcript = [
            {"role": "user", "content": "I want to talk to a human please"},
        ]
        assert detector.check(transcript) == HandoffReason.EXPLICIT_REQUEST

    def test_explicit_request_case_insensitive(self) -> None:
        detector = HandoffDetector()
        transcript = [
            {"role": "user", "content": "TALK TO A HUMAN"},
        ]
        assert detector.check(transcript) == HandoffReason.EXPLICIT_REQUEST

    def test_keyword_match(self) -> None:
        detector = HandoffDetector(keywords=["refund"])
        transcript = [
            {"role": "user", "content": "I need a refund for my order"},
        ]
        assert detector.check(transcript) == HandoffReason.KEYWORD_MATCH

    def test_repeated_failure_detected(self) -> None:
        detector = HandoffDetector(failure_threshold=3)
        repeated_message = "I don't understand"
        transcript = [
            {"role": "user", "content": repeated_message},
            {"role": "assistant", "content": "Let me try again."},
            {"role": "user", "content": repeated_message},
            {"role": "assistant", "content": "Let me try again."},
            {"role": "user", "content": repeated_message},
        ]
        assert detector.check(transcript) == HandoffReason.REPEATED_FAILURE

    def test_repeated_failure_below_threshold(self) -> None:
        detector = HandoffDetector(failure_threshold=3)
        repeated_message = "I don't understand"
        transcript = [
            {"role": "user", "content": repeated_message},
            {"role": "assistant", "content": "Let me try again."},
            {"role": "user", "content": repeated_message},
        ]
        assert detector.check(transcript) is None

    def test_explicit_takes_priority_over_keyword(self) -> None:
        detector = HandoffDetector(keywords=["human"])
        # "talk to a human" matches both explicit phrases and the keyword "human"
        transcript = [
            {"role": "user", "content": "I want to talk to a human"},
        ]
        result = detector.check(transcript)
        assert result == HandoffReason.EXPLICIT_REQUEST

    def test_empty_transcript(self) -> None:
        detector = HandoffDetector()
        assert detector.check([]) is None

    def test_no_user_messages(self) -> None:
        detector = HandoffDetector()
        transcript = [
            {"role": "assistant", "content": "Hello! How can I help you?"},
            {"role": "assistant", "content": "Please let me know if you need anything."},
        ]
        assert detector.check(transcript) is None

    def test_custom_failure_threshold(self) -> None:
        detector = HandoffDetector(failure_threshold=2)
        repeated_message = "same message"
        transcript = [
            {"role": "user", "content": repeated_message},
            {"role": "assistant", "content": "Response."},
            {"role": "user", "content": repeated_message},
        ]
        assert detector.check(transcript) == HandoffReason.REPEATED_FAILURE

    def test_event_stream_uses_same_detection_logic(self) -> None:
        detector = HandoffDetector()
        events = [
            ConversationEvent(role="user", content="I want to talk to a human", sequence_number=0),
        ]
        assert detector.check(events=events) == HandoffReason.EXPLICIT_REQUEST

    def test_events_to_transcript_preserves_order(self) -> None:
        events = [
            ConversationEvent(role="assistant", content="second", sequence_number=1),
            ConversationEvent(role="user", content="first", sequence_number=0),
        ]
        assert events_to_transcript(events) == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
