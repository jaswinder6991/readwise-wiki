"""Smoke tests for Celery task wiring.

The substantive work is tested in service-level tests; these tests verify the tasks
exist with the expected names, signatures, and that they run end-to-end with mocked
dependencies. The full chain orchestration is tested via the management command path.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import FakeLLMClient
from tests.factories import HighlightFactory, TopicFactory
from wiki import tasks
from wiki.services.readwise import NormalizedHighlight

pytestmark = pytest.mark.django_db


class TestTaskRegistration:
    def test_task_names_are_stable(self):
        # The names are stable contracts — beat schedules and external callers reference them.
        assert tasks.sync_readwise_task.name == "wiki.tasks.sync_readwise_task"
        assert tasks.classify_pending_task.name == "wiki.tasks.classify_pending_task"
        assert (
            tasks.summarize_pending_topics_task.name == "wiki.tasks.summarize_pending_topics_task"
        )
        assert tasks.write_wiki_task.name == "wiki.tasks.write_wiki_task"


class TestSyncReadwiseTask:
    def test_sync_task_returns_summary_dict(self):
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

        with (
            patch("wiki.tasks.ReadwiseClient") as ClientClass,
            patch("wiki.tasks.chain") as chain_mock,
        ):
            ClientClass.return_value.export.return_value = iter([norm])
            chain_mock.return_value.apply_async.return_value = None

            result = tasks.sync_readwise_task()

            assert result["fetched"] == 1
            assert result["new"] == 1


class TestClassifyPendingTask:
    def test_classify_task_uses_built_llm_client(self):
        h = HighlightFactory()
        fake = FakeLLMClient(
            [{"classifications": [{"ref": h.id, "topic": "T", "related_topics": []}]}]
        )

        with patch("wiki.tasks._build_llm_client", return_value=fake):
            result = tasks.classify_pending_task()

        assert result["batches"] == 1
        assert result["highlights"] == 1


class TestWriteWikiTask:
    def test_write_task_writes_files(self, tmp_wiki_dir):
        topic = TopicFactory(name="T", slug="t")
        HighlightFactory(topic=topic)

        result = tasks.write_wiki_task()

        assert (tmp_wiki_dir / "wiki" / "t.md").exists()
        assert result["output_dir"] == str(tmp_wiki_dir)
