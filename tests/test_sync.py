"""Tests for the sync service: upsert + SyncRun bookkeeping."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wiki.models import Highlight, SyncRun
from wiki.services.readwise import NormalizedHighlight, ReadwiseClient
from wiki.services.sync import sync_readwise

pytestmark = pytest.mark.django_db


def _norm(rid: int, text: str = "x") -> NormalizedHighlight:
    return NormalizedHighlight(
        readwise_id=rid,
        text=text,
        note="",
        tags=[],
        highlighted_at="2026-01-01T00:00:00Z",
        source_title="Book",
        source_author="Author",
        source_url="https://example.com",
    )


def _fake_client(highlights: list[NormalizedHighlight]) -> ReadwiseClient:
    client = MagicMock(spec=ReadwiseClient)
    client.export.return_value = iter(highlights)
    return client


class TestSync:
    def test_creates_new_highlights(self):
        client = _fake_client([_norm(1, "alpha"), _norm(2, "beta")])
        result = sync_readwise(client)

        assert Highlight.objects.count() == 2
        assert result.sync_run.fetched_count == 2
        assert result.sync_run.new_count == 2
        assert result.sync_run.finished_at is not None
        assert result.sync_run.error == ""

    def test_upserts_existing_highlights(self):
        sync_readwise(_fake_client([_norm(1, "original text")]))
        # Second sync with updated text — should update, not duplicate.
        sync_readwise(_fake_client([_norm(1, "updated text")]))

        assert Highlight.objects.count() == 1
        assert Highlight.objects.get(readwise_id=1).text == "updated text"

    def test_passes_updated_after_from_last_successful_run(self):
        first_client = _fake_client([_norm(1)])
        sync_readwise(first_client)

        second_client = _fake_client([_norm(2)])
        sync_readwise(second_client)

        # The second client should have been called with updated_after set
        # (the started_at of the first successful run).
        kwargs = second_client.export.call_args.kwargs
        assert "updated_after" in kwargs
        assert kwargs["updated_after"] is not None

    def test_records_error_and_reraises(self):
        client = MagicMock(spec=ReadwiseClient)

        def boom(*_a, **_k):
            yield _norm(1)
            raise RuntimeError("boom")

        client.export.side_effect = boom

        with pytest.raises(RuntimeError, match="boom"):
            sync_readwise(client)

        run = SyncRun.objects.latest("started_at")
        assert "boom" in run.error
        assert run.finished_at is not None
        assert run.fetched_count == 1
        # The one highlight that came in before the error should be persisted.
        assert Highlight.objects.filter(readwise_id=1).exists()

    def test_first_sync_passes_no_updated_after(self):
        client = _fake_client([_norm(1)])
        sync_readwise(client)

        kwargs = client.export.call_args.kwargs
        assert kwargs.get("updated_after") is None

    def test_skips_failed_runs_when_picking_updated_after(self):
        # A failed run should not be used as the watermark.
        bad_client = MagicMock(spec=ReadwiseClient)
        bad_client.export.side_effect = RuntimeError("nope")
        with pytest.raises(RuntimeError):
            sync_readwise(bad_client)

        good_client = _fake_client([_norm(1)])
        sync_readwise(good_client)

        kwargs = good_client.export.call_args.kwargs
        # No prior *successful* run, so updated_after stays None.
        assert kwargs.get("updated_after") is None
