"""Readwise /export/ API client.

Pulls highlights with cursor pagination and yields normalized dicts ready to be
upserted into the Highlight model.

API reference: https://readwise.io/api_deets
  GET /api/v2/export/?pageCursor=...&updatedAfter=...
  Auth: Authorization: Token <token>
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


@dataclass(frozen=True)
class NormalizedHighlight:
    """Wire-format highlight from Readwise, mapped to our domain shape."""

    readwise_id: int
    text: str
    note: str
    tags: list[str]
    highlighted_at: str | None
    source_title: str
    source_author: str
    source_url: str


class ReadwiseError(Exception):
    """Raised on non-2xx responses from the Readwise API."""


class ReadwiseClient:
    BASE_URL = "https://readwise.io/api/v2"
    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        if not token:
            raise ValueError("Readwise token is required")
        self.token = token
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Token {token}"})
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    def export(self, updated_after: datetime | str | None = None) -> Iterator[NormalizedHighlight]:
        """Yield every highlight, walking the cursor across all pages."""
        url = f"{self.base_url}/export/"
        params: dict[str, str] = {}
        if updated_after is not None:
            params["updatedAfter"] = (
                updated_after.isoformat() if isinstance(updated_after, datetime) else updated_after
            )

        next_cursor: str | None = None
        while True:
            page_params = dict(params)
            if next_cursor:
                page_params["pageCursor"] = next_cursor

            response = self.session.get(url, params=page_params, timeout=self.timeout)
            if response.status_code != 200:
                raise ReadwiseError(
                    f"Readwise /export/ returned {response.status_code}: {response.text[:200]}"
                )

            payload = response.json()
            for book in payload.get("results", []):
                for highlight in book.get("highlights", []):
                    yield self._normalize(highlight, book)

            next_cursor = payload.get("nextPageCursor")
            if not next_cursor:
                return

    @staticmethod
    def _normalize(highlight: dict[str, Any], book: dict[str, Any]) -> NormalizedHighlight:
        tags_raw = highlight.get("tags") or []
        tags = [t["name"] for t in tags_raw if isinstance(t, dict) and t.get("name")]
        return NormalizedHighlight(
            readwise_id=int(highlight["id"]),
            text=highlight.get("text") or "",
            note=highlight.get("note") or "",
            tags=tags,
            highlighted_at=highlight.get("highlighted_at"),
            source_title=book.get("title") or "",
            source_author=book.get("author") or "",
            source_url=(book.get("source_url") or book.get("unique_url") or ""),
        )
