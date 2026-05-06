"""Django admin registrations.

The admin is intentionally the inspection UI for this project — no custom dashboards,
just well-tuned `list_display` / `list_filter` so highlights, topics, classification
batches, and LLM call telemetry are easy to browse.
"""

from django.contrib import admin

from .models import ClassificationBatch, Highlight, LLMCall, SyncRun, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "highlight_count",
        "summary_generated_at",
        "needs_summary_regen",
        "updated_at",
    )
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")
    filter_horizontal = ("related_topics",)

    @admin.display(description="# highlights")
    def highlight_count(self, obj: Topic) -> int:
        return obj.highlights.count()


@admin.register(Highlight)
class HighlightAdmin(admin.ModelAdmin):
    list_display = (
        "readwise_id",
        "text_preview",
        "source_title",
        "topic",
        "classified_at",
        "highlighted_at",
    )
    list_filter = ("topic", "classified_at")
    search_fields = ("text", "source_title", "source_author", "note")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("topic",)

    @admin.display(description="text")
    def text_preview(self, obj: Highlight) -> str:
        return (obj.text[:80] + "…") if len(obj.text) > 80 else obj.text


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "finished_at",
        "fetched_count",
        "new_count",
        "has_error",
    )
    readonly_fields = (
        "started_at",
        "finished_at",
        "cursor_used",
        "next_cursor",
        "fetched_count",
        "new_count",
        "error",
    )

    @admin.display(boolean=True, description="error?")
    def has_error(self, obj: SyncRun) -> bool:
        return bool(obj.error)


@admin.register(ClassificationBatch)
class ClassificationBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "finished_at", "highlight_count", "succeeded")
    list_filter = ("succeeded",)
    readonly_fields = ("started_at", "finished_at", "succeeded", "error")
    filter_horizontal = ("highlights",)

    @admin.display(description="# highlights")
    def highlight_count(self, obj: ClassificationBatch) -> int:
        return obj.highlights.count()


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "purpose",
        "model_name",
        "total_tokens",
        "latency_ms",
        "cost_estimate_usd",
    )
    list_filter = ("purpose", "model_name")
    readonly_fields = (
        "purpose",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "cost_estimate_usd",
        "batch",
        "topic",
        "error",
        "created_at",
    )
