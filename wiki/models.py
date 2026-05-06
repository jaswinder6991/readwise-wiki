"""Domain models for the Readwise → Wiki pipeline.

Source of truth for highlights, topics, the topic graph, and per-LLM-call telemetry.
The Markdown wiki is a regenerable view over these tables.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class Topic(models.Model):
    """A topic page in the wiki — populated by classifying highlights."""

    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=120)

    summary = models.TextField(blank=True, default="")
    summary_generated_at = models.DateTimeField(null=True, blank=True)
    highlight_count_at_last_summary = models.PositiveIntegerField(default=0)

    related_topics = models.ManyToManyField("self", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def needs_summary_regen(self) -> bool:
        """True if enough new highlights have landed since the summary was generated."""
        threshold = settings.WIKI["SUMMARY_REGEN_THRESHOLD"]
        if self.summary_generated_at is None:
            return self.highlights.exists()
        new_since = self.highlights.count() - self.highlight_count_at_last_summary
        return new_since >= threshold


class Highlight(models.Model):
    """A single Readwise highlight, with its topic assignment."""

    readwise_id = models.BigIntegerField(unique=True, db_index=True)
    text = models.TextField()
    note = models.TextField(blank=True, default="")
    source_title = models.CharField(max_length=512, blank=True, default="")
    source_author = models.CharField(max_length=256, blank=True, default="")
    source_url = models.URLField(max_length=1024, blank=True, default="")
    tags = models.JSONField(default=list)
    highlighted_at = models.DateTimeField(null=True, blank=True)

    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="highlights",
    )
    classified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-highlighted_at", "-created_at"]
        indexes = [
            models.Index(fields=["topic", "-highlighted_at"]),
            models.Index(fields=["classified_at"]),
        ]

    def __str__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        return f"#{self.readwise_id}: {preview}"


class SyncRun(models.Model):
    """One pass of pulling highlights from Readwise."""

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cursor_used = models.CharField(max_length=512, blank=True, default="")
    next_cursor = models.CharField(max_length=512, blank=True, default="")
    fetched_count = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"SyncRun {self.pk} @ {self.started_at:%Y-%m-%d %H:%M}"


class ClassificationBatch(models.Model):
    """One batched LLM call that classified N highlights."""

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    highlights = models.ManyToManyField(Highlight, related_name="classification_batches")
    succeeded = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Batch {self.pk} @ {self.started_at:%Y-%m-%d %H:%M}"


class LLMCall(models.Model):
    """Per-call telemetry for every LLM invocation — tokens, latency, estimated cost.

    Centralized here so the Django admin gives an at-a-glance view of model spend.
    """

    PURPOSE_CLASSIFY = "classify"
    PURPOSE_SUMMARIZE = "summarize"
    PURPOSE_CHOICES = [
        (PURPOSE_CLASSIFY, "Classify highlights"),
        (PURPOSE_SUMMARIZE, "Summarize topic"),
    ]

    purpose = models.CharField(max_length=32, choices=PURPOSE_CHOICES)
    model_name = models.CharField(max_length=128)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_estimate_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))

    batch = models.ForeignKey(
        ClassificationBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_calls",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_calls",
    )

    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["purpose", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} {self.model_name} ({self.total_tokens} tok, {self.latency_ms}ms)"
