"""Pytest configuration and shared fixtures.

Sets DATABASE_URL to a file-backed sqlite before Django imports so tests don't need
a running Postgres (the production DB is Postgres; sqlite for tests is fine because
we use no Postgres-specific features).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

# Must run before Django is imported.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_db.sqlite3")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("READWISE_TOKEN", "test-readwise-token")

import pytest  # noqa: E402

from wiki.services.llm import LLMResult  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---- Fakes & test doubles ----


class FakeLLMClient:
    """Drop-in replacement for LLMClient. Returns scripted payloads in order.

    Records every call so tests can assert prompts, message counts, etc.
    """

    def __init__(self, scripted_payloads: list[dict] | None = None, *, model: str = "fake-model"):
        self._payloads = list(scripted_payloads or [])
        self.calls: list[dict] = []
        self.model = model

    def queue(self, payload: dict) -> None:
        self._payloads.append(payload)

    def complete_json(self, messages, *, model=None):
        self.calls.append({"messages": messages, "model": model or self.model})
        if not self._payloads:
            raise AssertionError(
                "FakeLLMClient: no scripted payload available for this call. "
                "Use .queue() or pass scripted_payloads in the constructor."
            )
        payload = self._payloads.pop(0)
        return LLMResult(
            payload=payload,
            model_name=self.model,
            prompt_tokens=42,
            completion_tokens=24,
            total_tokens=66,
            latency_ms=123,
            cost_estimate_usd=Decimal("0.000456"),
        )


# ---- Fixtures ----


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def tmp_wiki_dir(tmp_path, settings) -> Path:
    """Point WIKI['OUTPUT_DIR'] at a tmp dir for file-writing tests."""
    out = tmp_path / "wiki-project"
    settings.WIKI = {**settings.WIKI, "OUTPUT_DIR": out}
    return out


@pytest.fixture
def readwise_export_payload() -> dict:
    """Single-page Readwise /export/ payload — no nextPageCursor."""
    with (FIXTURES_DIR / "readwise_export.json").open() as f:
        return json.load(f)


@pytest.fixture
def readwise_export_two_pages() -> tuple[dict, dict]:
    """Two-page Readwise payload — page 1 has nextPageCursor."""
    page_one = {
        "count": 2,
        "nextPageCursor": "cursor-2",
        "results": [
            {
                "user_book_id": 100,
                "title": "Page One Book",
                "author": "Author A",
                "source_url": "https://example.com/a",
                "highlights": [
                    {
                        "id": 1001,
                        "text": "Highlight on page one",
                        "note": "",
                        "tags": [{"name": "philosophy"}],
                        "highlighted_at": "2026-01-15T10:00:00Z",
                    }
                ],
            }
        ],
    }
    page_two = {
        "count": 1,
        "nextPageCursor": None,
        "results": [
            {
                "user_book_id": 200,
                "title": "Page Two Book",
                "author": "Author B",
                "source_url": "https://example.com/b",
                "highlights": [
                    {
                        "id": 2001,
                        "text": "Highlight on page two",
                        "note": "",
                        "tags": [],
                        "highlighted_at": "2026-02-15T10:00:00Z",
                    }
                ],
            }
        ],
    }
    return page_one, page_two
