"""Tests for the threshold-gated topic summarizer."""

from __future__ import annotations

import pytest
from django.utils import timezone

from tests.conftest import FakeLLMClient
from tests.factories import HighlightFactory, TopicFactory
from wiki.models import LLMCall
from wiki.services.summarizer import Summarizer

pytestmark = pytest.mark.django_db


class TestSummarizer:
    def test_summarizes_topic_without_prior_summary(self, settings):
        settings.WIKI = {**settings.WIKI, "SUMMARY_REGEN_THRESHOLD": 5}
        topic = TopicFactory(name="Stoicism", slug="stoicism")
        HighlightFactory.create_batch(2, topic=topic)
        llm = FakeLLMClient([{"overview": "A philosophy of resilience."}])

        outcome = Summarizer(llm).summarize_topic(topic)

        topic.refresh_from_db()
        assert not outcome.skipped
        assert topic.summary == "A philosophy of resilience."
        assert topic.summary_generated_at is not None
        assert topic.highlight_count_at_last_summary == 2

    def test_skips_below_threshold(self, settings):
        settings.WIKI = {**settings.WIKI, "SUMMARY_REGEN_THRESHOLD": 5}
        topic = TopicFactory(name="Stoicism", slug="stoicism")
        topic.summary = "old summary"
        topic.summary_generated_at = timezone.now()
        topic.highlight_count_at_last_summary = 10
        topic.save()
        # Add only 2 new highlights — below the threshold of 5.
        HighlightFactory.create_batch(12, topic=topic)
        llm = FakeLLMClient()  # Should never be called.

        outcome = Summarizer(llm).summarize_topic(topic)

        assert outcome.skipped
        assert outcome.skip_reason == "below regen threshold"
        topic.refresh_from_db()
        assert topic.summary == "old summary"
        assert llm.calls == []

    def test_force_overrides_threshold(self, settings):
        settings.WIKI = {**settings.WIKI, "SUMMARY_REGEN_THRESHOLD": 5}
        topic = TopicFactory(name="Stoicism", slug="stoicism")
        topic.summary = "old"
        topic.summary_generated_at = timezone.now()
        topic.highlight_count_at_last_summary = 100
        topic.save()
        HighlightFactory.create_batch(1, topic=topic)
        llm = FakeLLMClient([{"overview": "fresh"}])

        outcome = Summarizer(llm).summarize_topic(topic, force=True)

        assert not outcome.skipped
        topic.refresh_from_db()
        assert topic.summary == "fresh"

    def test_skips_topic_with_no_highlights(self):
        topic = TopicFactory(name="Empty", slug="empty")
        llm = FakeLLMClient()

        outcome = Summarizer(llm).summarize_topic(topic, force=True)

        assert outcome.skipped
        assert outcome.skip_reason == "no highlights"
        assert llm.calls == []

    def test_records_llm_call(self):
        topic = TopicFactory(name="Stoicism", slug="stoicism")
        HighlightFactory(topic=topic)
        llm = FakeLLMClient([{"overview": "summary"}])

        Summarizer(llm).summarize_topic(topic)

        call = LLMCall.objects.get()
        assert call.purpose == LLMCall.PURPOSE_SUMMARIZE
        assert call.topic == topic
        assert call.total_tokens == 66

    def test_summarize_pending_only_acts_on_topics_past_threshold(self, settings):
        settings.WIKI = {**settings.WIKI, "SUMMARY_REGEN_THRESHOLD": 5}
        # Topic A: needs regen (no prior summary, has highlights)
        a = TopicFactory(name="A", slug="a")
        HighlightFactory.create_batch(3, topic=a)
        # Topic B: under threshold
        b = TopicFactory(name="B", slug="b")
        b.summary = "stable"
        b.summary_generated_at = timezone.now()
        b.highlight_count_at_last_summary = 10
        b.save()
        HighlightFactory.create_batch(11, topic=b)

        llm = FakeLLMClient([{"overview": "A summary"}])
        outcomes = Summarizer(llm).summarize_pending()

        regenerated = [o for o in outcomes if not o.skipped]
        assert {o.topic.slug for o in regenerated} == {"a"}
