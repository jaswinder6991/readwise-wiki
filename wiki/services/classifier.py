"""Batched LLM classification of highlights into topics.

Pipeline per batch:
  1. Build a prompt with N highlights.
  2. Ask the LLM for {classifications: [{ref, topic, related_topics}]}.
  3. For each result, resolve topic name → existing Topic (exact slug or fuzzy match)
     or create a new one.
  4. Assign Highlight.topic and aggregate related-topic edges into Topic.related_topics.
  5. Persist a ClassificationBatch + LLMCall row.

The fuzzy-match step is the load-bearing part — without it the wiki fragments into
"Decision Making" / "Decision-making" / "Decisions" almost immediately.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rapidfuzz import fuzz, process

from wiki.models import ClassificationBatch, Highlight, LLMCall, Topic
from wiki.services.llm import LLMClientProtocol

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a knowledge-organization assistant. Given a batch of reading highlights, "
    "classify each into a single primary topic and suggest 1–3 related topics. "
    "Topic names should be short noun phrases in Title Case (e.g. 'Decision Making', "
    "'Stoicism', 'Distributed Systems'). Reuse the same topic name across highlights "
    "when they belong together — do not invent slight variants. "
    "Respond ONLY with a JSON object of the form: "
    '{"classifications":[{"ref":<int>,"topic":"<name>","related_topics":["<name>",...]}]}.'
)


@dataclass(frozen=True)
class HighlightClassification:
    highlight_id: int
    topic_name: str
    related_topic_names: list[str]


@dataclass
class BatchOutcome:
    batch: ClassificationBatch
    classifications: list[HighlightClassification]
    topics_touched: list[Topic]


class Classifier:
    def __init__(
        self,
        llm: LLMClientProtocol,
        *,
        batch_size: int | None = None,
        fuzzy_threshold: int | None = None,
    ):
        self.llm = llm
        self.batch_size = batch_size or settings.WIKI["CLASSIFICATION_BATCH_SIZE"]
        self.fuzzy_threshold = fuzzy_threshold or settings.WIKI["TOPIC_FUZZY_MATCH_THRESHOLD"]

    # ---- Public API ----

    def classify_pending(self) -> list[BatchOutcome]:
        """Classify every unclassified highlight, in batches. Returns one outcome per batch."""
        outcomes: list[BatchOutcome] = []
        pending = list(Highlight.objects.filter(classified_at__isnull=True).order_by("id"))
        for batch in _chunked(pending, self.batch_size):
            outcomes.append(self.classify_batch(batch))
        return outcomes

    def classify_batch(self, highlights: list[Highlight]) -> BatchOutcome:
        """Classify exactly this list of highlights as one LLM call."""
        if not highlights:
            raise ValueError("classify_batch called with no highlights")

        batch = ClassificationBatch.objects.create()
        batch.highlights.set(highlights)

        try:
            result = self.llm.complete_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(highlights)},
                ]
            )
        except Exception as exc:  # noqa: BLE001 — record + re-raise
            batch.error = repr(exc)
            batch.finished_at = timezone.now()
            batch.save()
            raise

        # Persist the LLMCall row regardless of parse success.
        LLMCall.objects.create(
            purpose=LLMCall.PURPOSE_CLASSIFY,
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
            cost_estimate_usd=result.cost_estimate_usd,
            batch=batch,
        )

        try:
            classifications = self._parse(result.payload, highlights)
            topics_touched = self._apply(classifications)
        except Exception as exc:  # noqa: BLE001
            batch.error = f"parse/apply failed: {exc!r}\nraw: {json.dumps(result.payload)[:500]}"
            batch.finished_at = timezone.now()
            batch.save()
            raise

        batch.succeeded = True
        batch.finished_at = timezone.now()
        batch.save()
        return BatchOutcome(
            batch=batch, classifications=classifications, topics_touched=topics_touched
        )

    # ---- Topic resolution: the load-bearing dedup logic ----

    def resolve_topic(self, name: str) -> Topic:
        """Normalize → exact slug match → fuzzy match → create."""
        canonical = self._normalize(name)
        slug = slugify(canonical) or "untitled"

        existing = Topic.objects.filter(slug=slug).first()
        if existing:
            return existing

        candidates = list(Topic.objects.values_list("name", "slug"))
        if candidates:
            names = [c[0] for c in candidates]
            match = process.extractOne(canonical, names, scorer=fuzz.WRatio)
            if match is not None:
                _, score, idx = match
                if score >= self.fuzzy_threshold:
                    return Topic.objects.get(slug=candidates[idx][1])

        return Topic.objects.create(slug=slug, name=canonical)

    # ---- Internals ----

    @staticmethod
    def _normalize(name: str) -> str:
        return " ".join(name.strip().split()).title()

    @staticmethod
    def _build_user_prompt(highlights: list[Highlight]) -> str:
        lines = [
            "Classify the following highlights. Respond with JSON as instructed.",
            "Each highlight is keyed by 'ref' — use the same ref in your response.",
            "",
        ]
        for h in highlights:
            source = f" — {h.source_title}" if h.source_title else ""
            text = h.text.replace("\n", " ").strip()
            lines.append(f'ref={h.id}: "{text}"{source}')
        return "\n".join(lines)

    @staticmethod
    def _parse(payload: dict, highlights: list[Highlight]) -> list[HighlightClassification]:
        items = payload.get("classifications") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ValueError(f"expected 'classifications' list, got: {type(payload).__name__}")

        by_id = {h.id: h for h in highlights}
        out: list[HighlightClassification] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                ref = int(item["ref"])
            except (KeyError, TypeError, ValueError):
                continue
            if ref not in by_id:
                logger.warning("classifier returned unknown ref=%s; skipping", ref)
                continue
            topic_name = (item.get("topic") or "").strip()
            if not topic_name:
                continue
            related = item.get("related_topics") or []
            related_names = [str(r).strip() for r in related if isinstance(r, str) and r.strip()]
            out.append(
                HighlightClassification(
                    highlight_id=ref,
                    topic_name=topic_name,
                    related_topic_names=related_names,
                )
            )
        return out

    @transaction.atomic
    def _apply(self, classifications: Iterable[HighlightClassification]) -> list[Topic]:
        """Resolve topics, set Highlight.topic, aggregate related-topic edges."""
        edges: dict[int, set[int]] = defaultdict(set)
        touched_ids: set[int] = set()
        now = timezone.now()

        for c in classifications:
            primary = self.resolve_topic(c.topic_name)
            touched_ids.add(primary.id)

            Highlight.objects.filter(id=c.highlight_id).update(topic=primary, classified_at=now)

            for related_name in c.related_topic_names:
                related = self.resolve_topic(related_name)
                if related.id == primary.id:
                    continue
                touched_ids.add(related.id)
                edges[primary.id].add(related.id)

        # Add edges (symmetrical M:N — adding one direction is enough).
        for primary_id, related_ids in edges.items():
            primary = Topic.objects.get(id=primary_id)
            for related_id in related_ids:
                primary.related_topics.add(related_id)

        return list(Topic.objects.filter(id__in=touched_ids))


def _chunked(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
