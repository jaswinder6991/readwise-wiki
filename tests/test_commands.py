"""Smoke tests for management commands."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.conftest import FakeLLMClient
from tests.factories import HighlightFactory
from wiki.services.readwise import NormalizedHighlight

pytestmark = pytest.mark.django_db


class TestInitWikiCommand:
    def test_creates_skeleton(self, tmp_wiki_dir):
        out = StringIO()
        call_command("init_wiki", stdout=out)
        assert (tmp_wiki_dir / "CLAUDE.md").exists()
        assert "Initialized" in out.getvalue()


class TestSyncReadwiseCommand:
    def test_inline_sync_runs_full_pipeline(self, tmp_wiki_dir, settings):
        settings.READWISE_TOKEN = "test-token"
        settings.LLM = {**settings.LLM, "API_KEY": "test-key", "MODEL": "test-model"}
        norm = NormalizedHighlight(
            readwise_id=1,
            text="A highlight",
            note="",
            tags=[],
            highlighted_at=None,
            source_title="Book",
            source_author="Author",
            source_url="",
        )
        # Pre-create the highlight so we know its pk before scripting the LLM payload —
        # don't rely on auto-increment landing at 1 in a fresh DB.
        existing = HighlightFactory(readwise_id=1)
        fake_llm = FakeLLMClient(
            [
                {
                    "classifications": [
                        {"ref": existing.id, "topic": "Topic A", "related_topics": []}
                    ]
                },
                {"overview": "A short overview."},
            ]
        )

        out = StringIO()
        with (
            patch("wiki.management.commands.sync_readwise.ReadwiseClient") as RWClass,
            patch("wiki.management.commands.sync_readwise.LLMClient", return_value=fake_llm),
        ):
            RWClass.return_value.export.return_value = iter([norm])
            call_command("sync_readwise", stdout=out)

        output = out.getvalue()
        assert "Sync:" in output
        assert "Wiki written to" in output

    def test_skip_llm_flag_bypasses_classification(self, tmp_wiki_dir, settings):
        settings.READWISE_TOKEN = "test-token"
        norm = NormalizedHighlight(
            readwise_id=1,
            text="t",
            note="",
            tags=[],
            highlighted_at=None,
            source_title="",
            source_author="",
            source_url="",
        )

        out = StringIO()
        with patch("wiki.management.commands.sync_readwise.ReadwiseClient") as RWClass:
            RWClass.return_value.export.return_value = iter([norm])
            call_command("sync_readwise", "--skip-llm", stdout=out)

        # No LLM client constructed, no classifier run.
        assert "Classify" not in out.getvalue()
        assert (tmp_wiki_dir / "wiki").exists()

    def test_async_flag_enqueues_task(self):
        out = StringIO()
        with patch("wiki.management.commands.sync_readwise.sync_readwise_task") as task_mock:
            task_mock.delay.return_value.id = "fake-task-id"
            call_command("sync_readwise", "--async", stdout=out)

        task_mock.delay.assert_called_once()
        assert "fake-task-id" in out.getvalue()

    def test_missing_readwise_token_errors(self, settings):
        settings.READWISE_TOKEN = ""
        with pytest.raises(CommandError, match="READWISE_TOKEN"):
            call_command("sync_readwise")
