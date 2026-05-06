"""Topic summary generation, threshold-gated.

A topic gets a fresh summary only when at least SUMMARY_REGEN_THRESHOLD new highlights
have landed on it since the last summary was written. Saves tokens and keeps summaries
stable until enough new evidence accumulates.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from wiki.models import LLMCall, Topic
from wiki.services.llm import LLMClientProtocol

SYSTEM_PROMPT = (
    "You write concise, agent-readable wiki overviews for knowledge topics. "
    "Given a topic name and a sample of highlights about it, produce a 2–4 sentence "
    "overview that captures what the topic is about, *as evidenced by the highlights*. "
    "Do not invent claims not supported by the highlights. "
    'Respond ONLY with JSON: {"overview":"<text>"}.'
)


@dataclass
class SummaryOutcome:
    topic: Topic
    overview: str
    skipped: bool = False
    skip_reason: str = ""


class Summarizer:
    def __init__(self, llm: LLMClientProtocol):
        self.llm = llm

    def summarize_pending(self) -> list[SummaryOutcome]:
        """Re-summarize every topic whose threshold has been crossed."""
        outcomes: list[SummaryOutcome] = []
        for topic in Topic.objects.all():
            outcome = self.summarize_topic(topic)
            outcomes.append(outcome)
        return outcomes

    def summarize_topic(self, topic: Topic, *, force: bool = False) -> SummaryOutcome:
        if not force and not topic.needs_summary_regen:
            return SummaryOutcome(
                topic=topic,
                overview=topic.summary,
                skipped=True,
                skip_reason="below regen threshold",
            )

        highlights = list(topic.highlights.all().order_by("-highlighted_at")[:25])
        if not highlights:
            return SummaryOutcome(
                topic=topic, overview="", skipped=True, skip_reason="no highlights"
            )

        prompt = self._build_prompt(topic, highlights)
        result = self.llm.complete_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        LLMCall.objects.create(
            purpose=LLMCall.PURPOSE_SUMMARIZE,
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
            cost_estimate_usd=result.cost_estimate_usd,
            topic=topic,
        )

        overview = (
            (result.payload or {}).get("overview", "").strip()
            if isinstance(result.payload, dict)
            else ""
        )
        if not overview:
            return SummaryOutcome(
                topic=topic, overview="", skipped=True, skip_reason="empty LLM overview"
            )

        topic.summary = overview
        topic.summary_generated_at = timezone.now()
        topic.highlight_count_at_last_summary = topic.highlights.count()
        topic.save(
            update_fields=[
                "summary",
                "summary_generated_at",
                "highlight_count_at_last_summary",
                "updated_at",
            ]
        )
        return SummaryOutcome(topic=topic, overview=overview)

    @staticmethod
    def _build_prompt(topic: Topic, highlights: list) -> str:
        lines = [f'Topic: "{topic.name}"', "", "Highlights:"]
        for h in highlights:
            text = h.text.replace("\n", " ").strip()
            source = f" — {h.source_title}" if h.source_title else ""
            lines.append(f'- "{text}"{source}')
        return "\n".join(lines)
