"""Tests for the Classifier — the AI-headline service.

Coverage focus: batching, normalization, fuzzy dedup, related-topic edges,
LLMCall persistence, error paths.
"""

from __future__ import annotations

import pytest

from tests.conftest import FakeLLMClient
from tests.factories import HighlightFactory, TopicFactory
from wiki.models import ClassificationBatch, Highlight, LLMCall, Topic
from wiki.services.classifier import Classifier

pytestmark = pytest.mark.django_db


def _classification_payload(items: list[tuple[int, str, list[str]]]) -> dict:
    return {
        "classifications": [
            {"ref": ref, "topic": topic, "related_topics": related} for ref, topic, related in items
        ]
    }


class TestClassifyBatch:
    def test_assigns_topic_and_creates_topic_record(self):
        h = HighlightFactory(text="A highlight about decisions")
        llm = FakeLLMClient([_classification_payload([(h.id, "Decision Making", [])])])

        outcome = Classifier(llm).classify_batch([h])

        h.refresh_from_db()
        assert h.topic is not None
        assert h.topic.name == "Decision Making"
        assert h.topic.slug == "decision-making"
        assert h.classified_at is not None
        assert outcome.batch.succeeded
        assert outcome.batch.error == ""

    def test_writes_llm_call_telemetry(self):
        h = HighlightFactory()
        llm = FakeLLMClient([_classification_payload([(h.id, "Topic", [])])])

        Classifier(llm).classify_batch([h])

        call = LLMCall.objects.get()
        assert call.purpose == LLMCall.PURPOSE_CLASSIFY
        assert call.model_name == "fake-model"
        assert call.total_tokens == 66
        assert call.latency_ms == 123
        assert call.batch is not None

    def test_drops_related_topic_names_that_dont_match_a_primary(self):
        # Only one primary in this batch ("Decision Making"). The related names
        # "Psychology" and "Cognitive Bias" don't match any existing primary,
        # so they should be dropped — not materialized as empty Topic rows.
        h = HighlightFactory(text="bridges decisions and psychology")
        llm = FakeLLMClient(
            [_classification_payload([(h.id, "Decision Making", ["Psychology", "Cognitive Bias"])])]
        )

        Classifier(llm).classify_batch([h])

        # Only the primary exists. No shadow topics for related-only names.
        assert Topic.objects.count() == 1
        primary = Topic.objects.get(slug="decision-making")
        assert primary.related_topics.count() == 0

    def test_adds_edges_between_topics_that_are_both_primaries(self):
        # Two highlights in the same batch — A's primary is "Decision Making" with
        # related "Psychology"; B's primary is "Psychology" with related "Decision
        # Making". Both topics are primaries in this batch, so the edge should form.
        h1 = HighlightFactory(text="A decision-y highlight")
        h2 = HighlightFactory(text="A psychology-y highlight")
        llm = FakeLLMClient(
            [
                _classification_payload(
                    [
                        (h1.id, "Decision Making", ["Psychology"]),
                        (h2.id, "Psychology", ["Decision Making"]),
                    ]
                )
            ]
        )

        Classifier(llm).classify_batch([h1, h2])

        decision_making = Topic.objects.get(slug="decision-making")
        psychology = Topic.objects.get(slug="psychology")
        assert psychology in decision_making.related_topics.all()
        # M:N is symmetrical — the reverse edge is implicit.
        assert decision_making in psychology.related_topics.all()
        assert Topic.objects.count() == 2

    def test_empty_batch_raises(self):
        llm = FakeLLMClient([{"classifications": []}])
        with pytest.raises(ValueError, match="no highlights"):
            Classifier(llm).classify_batch([])

    def test_records_error_on_llm_failure(self):
        h = HighlightFactory()

        class BoomLLM(FakeLLMClient):
            def complete_json(self, *_a, **_k):
                raise RuntimeError("rate limited")

        with pytest.raises(RuntimeError):
            Classifier(BoomLLM()).classify_batch([h])

        batch = ClassificationBatch.objects.get()
        assert "rate limited" in batch.error
        assert batch.succeeded is False

    def test_skips_unknown_refs_returned_by_llm(self):
        h = HighlightFactory()
        llm = FakeLLMClient(
            [
                _classification_payload(
                    [
                        (h.id, "Real Topic", []),
                        (99_999, "Hallucinated Topic", []),
                    ]
                )
            ]
        )

        outcome = Classifier(llm).classify_batch([h])

        # Only the real ref applied.
        assert len(outcome.classifications) == 1
        assert outcome.classifications[0].highlight_id == h.id
        # Hallucinated topic must not have been created.
        assert not Topic.objects.filter(slug="hallucinated-topic").exists()

    def test_invalid_payload_shape_marks_batch_failed(self):
        h = HighlightFactory()
        llm = FakeLLMClient([{"wrong_key": "wrong_shape"}])

        with pytest.raises(ValueError):
            Classifier(llm).classify_batch([h])

        assert ClassificationBatch.objects.get().succeeded is False

    def test_empty_topic_name_is_skipped(self):
        h1 = HighlightFactory()
        h2 = HighlightFactory()
        llm = FakeLLMClient(
            [
                _classification_payload(
                    [
                        (h1.id, "Real Topic", []),
                        (h2.id, "", []),  # blank topic — should be skipped
                    ]
                )
            ]
        )

        Classifier(llm).classify_batch([h1, h2])

        h1.refresh_from_db()
        h2.refresh_from_db()
        assert h1.topic is not None
        assert h2.topic is None


class TestTopicResolution:
    def test_exact_slug_returns_existing_topic(self):
        existing = TopicFactory(name="Decision Making", slug="decision-making")
        c = Classifier(FakeLLMClient())

        resolved = c.resolve_topic("decision making")

        assert resolved.id == existing.id
        assert Topic.objects.count() == 1

    def test_normalizes_to_title_case(self):
        c = Classifier(FakeLLMClient())
        resolved = c.resolve_topic("decision   making")
        assert resolved.name == "Decision Making"
        assert resolved.slug == "decision-making"

    def test_fuzzy_dedup_prevents_near_duplicate(self):
        TopicFactory(name="Decision Making", slug="decision-making")
        c = Classifier(FakeLLMClient(), fuzzy_threshold=85)

        resolved = c.resolve_topic("Decision-Making")  # different slug, near-identical name

        assert Topic.objects.count() == 1
        assert resolved.slug == "decision-making"

    def test_below_fuzzy_threshold_creates_new_topic(self):
        TopicFactory(name="Stoicism", slug="stoicism")
        c = Classifier(FakeLLMClient(), fuzzy_threshold=95)

        resolved = c.resolve_topic("Distributed Systems")

        assert Topic.objects.count() == 2
        assert resolved.name == "Distributed Systems"


class TestClassifyPending:
    def test_only_picks_up_unclassified_highlights(self):
        already_classified = HighlightFactory(
            classified_at="2026-01-01T00:00:00Z",
            topic=TopicFactory(name="Existing", slug="existing"),
        )
        pending = HighlightFactory()

        llm = FakeLLMClient([_classification_payload([(pending.id, "New", [])])])
        outcomes = Classifier(llm).classify_pending()

        assert len(outcomes) == 1
        assert {c.highlight_id for c in outcomes[0].classifications} == {pending.id}
        already_classified.refresh_from_db()
        assert already_classified.topic.name == "Existing"  # unchanged

    def test_chunks_into_multiple_batches(self):
        highlights = HighlightFactory.create_batch(5)
        llm = FakeLLMClient(
            [
                _classification_payload([(h.id, f"T{h.id}", []) for h in highlights[:2]]),
                _classification_payload([(h.id, f"T{h.id}", []) for h in highlights[2:4]]),
                _classification_payload([(h.id, f"T{h.id}", []) for h in highlights[4:]]),
            ]
        )

        outcomes = Classifier(llm, batch_size=2).classify_pending()

        assert len(outcomes) == 3
        assert Highlight.objects.filter(classified_at__isnull=False).count() == 5
