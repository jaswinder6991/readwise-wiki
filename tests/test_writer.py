"""Tests for the WikiWriter — DB → Markdown rendering."""

from __future__ import annotations

import pytest

from tests.factories import HighlightFactory, TopicFactory
from wiki.services.writer import WikiWriter

pytestmark = pytest.mark.django_db


class TestInitSkeleton:
    def test_creates_directory_layout(self, tmp_wiki_dir):
        WikiWriter().init_skeleton()

        assert tmp_wiki_dir.exists()
        assert (tmp_wiki_dir / "raw").is_dir()
        assert (tmp_wiki_dir / "wiki").is_dir()
        assert (tmp_wiki_dir / "data").is_dir()
        assert (tmp_wiki_dir / "CLAUDE.md").exists()
        assert (tmp_wiki_dir / "index.md").exists()

    def test_claude_md_warns_db_is_source_of_truth(self, tmp_wiki_dir):
        WikiWriter().init_skeleton()
        content = (tmp_wiki_dir / "CLAUDE.md").read_text()
        assert "source of truth" in content.lower()
        assert "will be overwritten" in content.lower()

    def test_init_skeleton_idempotent(self, tmp_wiki_dir):
        WikiWriter().init_skeleton()
        (tmp_wiki_dir / "index.md").write_text("# Custom index — preserve me")
        WikiWriter().init_skeleton()
        # init_skeleton should not clobber an existing index.md
        assert "Custom index" in (tmp_wiki_dir / "index.md").read_text()


class TestWriteAll:
    def test_writes_topic_pages_with_highlights(self, tmp_wiki_dir):
        topic = TopicFactory(name="Stoicism", slug="stoicism", summary="Endure.")
        HighlightFactory(text="Memento mori.", topic=topic, source_title="Meditations")

        WikiWriter().write_all()

        page = (tmp_wiki_dir / "wiki" / "stoicism.md").read_text()
        assert "# Stoicism" in page
        assert "## Overview\nEndure." in page
        assert "Memento mori." in page
        assert "*Meditations*" in page

    def test_writes_related_topics_as_markdown_links(self, tmp_wiki_dir):
        a = TopicFactory(name="Decision Making", slug="decision-making")
        b = TopicFactory(name="Cognitive Bias", slug="cognitive-bias")
        a.related_topics.add(b)
        HighlightFactory(topic=a)
        HighlightFactory(topic=b)

        WikiWriter().write_all()

        page = (tmp_wiki_dir / "wiki" / "decision-making.md").read_text()
        assert "## Related Topics" in page
        # Standard Markdown link, peer-relative path, not [[wikilink]].
        assert "[Cognitive Bias](cognitive-bias.md)" in page

    def test_writes_index_with_topics_that_have_highlights(self, tmp_wiki_dir):
        a = TopicFactory(name="A", slug="a")
        b = TopicFactory(name="B", slug="b")
        HighlightFactory(topic=a)
        HighlightFactory(topic=b)

        WikiWriter().write_all()

        index = (tmp_wiki_dir / "index.md").read_text()
        assert "[A](wiki/a.md)" in index
        assert "[B](wiki/b.md)" in index

    def test_skips_pages_for_related_only_topics(self, tmp_wiki_dir):
        # Topic with primary highlight earns a page.
        primary = TopicFactory(name="Courage", slug="courage")
        HighlightFactory(topic=primary)
        # Related-only topic — exists as a graph node, has no primary highlights.
        # (After the classifier fix, the classifier won't create such topics, but
        # they can still exist if a user adds an edge manually via admin or if a
        # topic loses its last highlight. The writer must still handle the case.)
        related_only = TopicFactory(name="Wisdom", slug="wisdom")
        primary.related_topics.add(related_only)

        WikiWriter().write_all()

        assert (tmp_wiki_dir / "wiki" / "courage.md").exists()
        assert not (tmp_wiki_dir / "wiki" / "wisdom.md").exists()
        # The link to Wisdom still appears in courage.md as a Markdown link, even
        # though its target file doesn't exist — dangling-link pattern.
        assert "[Wisdom](wisdom.md)" in (tmp_wiki_dir / "wiki" / "courage.md").read_text()
        # Index lists only topics that earned a page.
        index = (tmp_wiki_dir / "index.md").read_text()
        assert "[Courage](wiki/courage.md)" in index
        assert "wisdom.md" not in index

    def test_writes_raw_highlights_file(self, tmp_wiki_dir):
        topic = TopicFactory(name="X", slug="x")
        HighlightFactory(
            readwise_id=42,
            text="Quotable quote.",
            source_title="Some Book",
            source_author="Some Author",
            tags=["tag-a", "tag-b"],
            topic=topic,
        )

        WikiWriter().write_all()

        raw = (tmp_wiki_dir / "raw" / "highlights.md").read_text()
        assert "# Raw Highlights" in raw
        assert "Quotable quote." in raw
        assert "Some Book — Some Author" in raw
        assert "tag-a, tag-b" in raw
        assert "ReadwiseID: 42" in raw

    def test_pending_summary_placeholder_when_summary_blank(self, tmp_wiki_dir):
        topic = TopicFactory(name="X", slug="x", summary="")
        HighlightFactory(topic=topic)

        WikiWriter().write_all()

        page = (tmp_wiki_dir / "wiki" / "x.md").read_text()
        assert "summary pending" in page.lower()

    def test_full_regen_removes_stale_topic_files(self, tmp_wiki_dir):
        topic = TopicFactory(name="Old", slug="old")
        HighlightFactory(topic=topic)
        WikiWriter().write_all()
        assert (tmp_wiki_dir / "wiki" / "old.md").exists()

        # Topic deleted from DB → next write should remove the orphan file.
        topic.delete()
        WikiWriter().write_all()
        assert not (tmp_wiki_dir / "wiki" / "old.md").exists()

    def test_idempotent_writes_produce_identical_output(self, tmp_wiki_dir):
        topic = TopicFactory(name="X", slug="x", summary="hello")
        HighlightFactory(topic=topic)

        WikiWriter().write_all()
        first = (tmp_wiki_dir / "wiki" / "x.md").read_text()
        WikiWriter().write_all()
        second = (tmp_wiki_dir / "wiki" / "x.md").read_text()

        assert first == second
