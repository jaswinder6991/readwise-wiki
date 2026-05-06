"""Tests for the Readwise HTTP client and normalization."""

from __future__ import annotations

import pytest
import responses

from wiki.services.readwise import ReadwiseClient, ReadwiseError


class TestReadwiseClient:
    @responses.activate
    def test_export_yields_normalized_highlights(self, readwise_export_payload):
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json=readwise_export_payload,
            status=200,
        )

        client = ReadwiseClient(token="abc")
        out = list(client.export())

        assert len(out) == 4
        first = out[0]
        assert first.readwise_id == 1001
        assert "Nothing in life" in first.text
        assert first.source_title == "Thinking, Fast and Slow"
        assert first.source_author == "Daniel Kahneman"
        assert first.tags == ["decisions", "psychology"]

        # source_url falls back to unique_url when source_url is empty
        meditations = [h for h in out if h.source_title == "Meditations"][0]
        assert meditations.source_url == "https://example.com/meditations-unique"

    @responses.activate
    def test_export_walks_pagination(self, readwise_export_two_pages):
        page_one, page_two = readwise_export_two_pages
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json=page_one,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json=page_two,
            status=200,
        )

        client = ReadwiseClient(token="abc")
        out = list(client.export())

        assert [h.readwise_id for h in out] == [1001, 2001]
        # Confirm the second request carried pageCursor=cursor-2
        assert "pageCursor=cursor-2" in responses.calls[1].request.url

    @responses.activate
    def test_export_passes_updated_after(self, readwise_export_payload):
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json=readwise_export_payload,
            status=200,
        )

        client = ReadwiseClient(token="abc")
        list(client.export(updated_after="2026-01-01T00:00:00Z"))

        assert "updatedAfter=2026-01-01T00%3A00%3A00Z" in responses.calls[0].request.url

    @responses.activate
    def test_export_raises_on_non_200(self):
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json={"detail": "Invalid token"},
            status=401,
        )

        client = ReadwiseClient(token="bad")
        with pytest.raises(ReadwiseError, match="401"):
            list(client.export())

    @responses.activate
    def test_export_handles_missing_optional_fields(self):
        payload = {
            "count": 1,
            "nextPageCursor": None,
            "results": [
                {
                    "user_book_id": 1,
                    "title": "Untitled",
                    "author": None,
                    "highlights": [{"id": 99, "text": "Bare highlight", "tags": None}],
                }
            ],
        }
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json=payload,
            status=200,
        )

        out = list(ReadwiseClient(token="abc").export())
        assert len(out) == 1
        assert out[0].tags == []
        assert out[0].source_author == ""
        assert out[0].note == ""

    def test_token_required(self):
        with pytest.raises(ValueError, match="Readwise token is required"):
            ReadwiseClient(token="")

    @responses.activate
    def test_authorization_header_is_set(self):
        responses.add(
            responses.GET,
            "https://readwise.io/api/v2/export/",
            json={"count": 0, "results": [], "nextPageCursor": None},
            status=200,
        )

        client = ReadwiseClient(token="my-secret")
        list(client.export())

        sent = responses.calls[0].request
        assert sent.headers["Authorization"] == "Token my-secret"
