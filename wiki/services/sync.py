"""Persist Readwise highlights into the DB.

Separated from the HTTP client so the client stays pure (no Django imports) and is
trivially testable; this module owns the upsert + SyncRun bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from wiki.models import Highlight, SyncRun
from wiki.services.readwise import NormalizedHighlight, ReadwiseClient


@dataclass
class SyncResult:
    sync_run: SyncRun
    new_highlight_ids: list[int]


def sync_readwise(client: ReadwiseClient) -> SyncResult:
    """Pull every highlight (or every highlight since the last successful run) and upsert."""
    last_successful = (
        SyncRun.objects.filter(error="", finished_at__isnull=False).order_by("-started_at").first()
    )
    updated_after = last_successful.started_at if last_successful else None

    sync_run = SyncRun.objects.create()
    new_ids: list[int] = []
    fetched = 0

    try:
        for normalized in client.export(updated_after=updated_after):
            fetched += 1
            highlight, created = _upsert(normalized)
            if created:
                new_ids.append(highlight.id)
    except Exception as exc:  # noqa: BLE001 — record then re-raise
        sync_run.error = repr(exc)
        sync_run.fetched_count = fetched
        sync_run.finished_at = timezone.now()
        sync_run.save()
        raise

    sync_run.fetched_count = fetched
    sync_run.new_count = len(new_ids)
    sync_run.finished_at = timezone.now()
    sync_run.save()
    return SyncResult(sync_run=sync_run, new_highlight_ids=new_ids)


def _upsert(n: NormalizedHighlight) -> tuple[Highlight, bool]:
    highlighted_at = parse_datetime(n.highlighted_at) if n.highlighted_at else None
    return Highlight.objects.update_or_create(
        readwise_id=n.readwise_id,
        defaults={
            "text": n.text,
            "note": n.note,
            "tags": n.tags,
            "highlighted_at": highlighted_at,
            "source_title": n.source_title,
            "source_author": n.source_author,
            "source_url": n.source_url,
        },
    )
