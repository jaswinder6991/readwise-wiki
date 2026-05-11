"""Render the DB to a Wikiwise-compatible Markdown wiki on disk.

Idempotency policy: full DB-driven regen on every call. The DB is the source of truth;
direct edits to .md files will be overwritten. CLAUDE.md tells the agent this explicitly
and points it at Django admin / code as the place to make persistent improvements.

Output layout:
  {OUTPUT_DIR}/
    index.md          ← topic list + agent pointer
    CLAUDE.md         ← agent instructions
    raw/
      highlights.md   ← every highlight, raw
    wiki/
      {slug}.md       ← one per topic: overview, highlights, related
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db.models import Count

from wiki.models import Highlight, Topic

CLAUDE_MD = """\
# Instructions for the LLM Agent

This is a knowledge wiki generated from Readwise highlights.

## Structure

- `/raw/highlights.md` — every highlight, raw, untouched.
- `/wiki/{topic}.md`   — one page per topic: overview, highlights, related topics.
- `/index.md`          — list of all topics.

## How this wiki is maintained

**The database is the source of truth.** This wiki is regenerated from a Postgres
database on every sync. Direct edits to `.md` files **will be overwritten** the next
time the pipeline runs.

To make persistent improvements:

- Edit topics, highlights, and topic-graph edges through the Django admin at `/admin/`
  (you'll need a superuser — `python manage.py createsuperuser` — the first time).
- For structural changes (renaming the topic schema, changing the writer template,
  adjusting classification prompts), commit code changes — the relevant code lives in
  `wiki/services/` and `wiki/models.py`.

## Tasks where you can help

- **Topic merges:** spot near-duplicate topics (e.g. "Decisions" and "Decision Making")
  and propose a merge. The classifier dedups on creation but older topics may need
  manual reconciliation.
- **Topic renames:** if a topic name reads awkwardly (e.g. "Misc Stuff"), suggest a
  better name based on its highlights.
- **Related-topic edges:** if you see a strong connection between two topics that the
  classifier missed, propose adding an edge.
- **Source-title cleanup:** highlights from web articles sometimes have noisy titles;
  flag candidates for cleanup.

## Rules

- Markdown only.
- Cross-page links use standard Markdown: `[Topic Name](slug.md)` from a sibling
  wiki page, or `[Topic Name](wiki/slug.md)` from `index.md` at the root. This
  trades pure Wikiwise `[[wikilink]]` convention for clickable links in any
  Markdown viewer (GitHub, IDE preview, etc.).
- Don't fabricate highlights. The raw file is the ground truth.
"""


class WikiWriter:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = Path(output_dir) if output_dir else settings.WIKI["OUTPUT_DIR"]
        self.raw_dir = self.output_dir / "raw"
        self.wiki_dir = self.output_dir / "wiki"
        self.data_dir = self.output_dir / "data"

    # ---- Public entry points ----

    def init_skeleton(self) -> None:
        """Create the directory layout and CLAUDE.md if not yet present."""
        for directory in (self.output_dir, self.raw_dir, self.wiki_dir, self.data_dir):
            directory.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "CLAUDE.md").write_text(CLAUDE_MD)
        index_path = self.output_dir / "index.md"
        if not index_path.exists():
            index_path.write_text(_render_empty_index())

    def write_all(self) -> None:
        """Regenerate everything from the DB.

        Only topics with at least one primary highlight earn a page. Related-only
        topics still exist as graph nodes (and can appear as `[[wikilinks]]` on other
        pages, which dangle until the topic accumulates its own highlights — this
        matches Karpathy/Wikiwise convention).
        """
        self.init_skeleton()
        self._write_raw()
        topics = list(
            Topic.objects.annotate(h_count=Count("highlights"))
            .filter(h_count__gt=0)
            .prefetch_related("highlights", "related_topics")
        )
        # Remove any topic file no longer represented in the DB (or no longer
        # qualifying for a page — e.g. a topic that lost its last highlight).
        existing_files = {p for p in self.wiki_dir.glob("*.md")}
        kept_files = set()
        for topic in topics:
            path = self._write_topic(topic)
            kept_files.add(path)
        for stale in existing_files - kept_files:
            stale.unlink()
        self._write_index(topics)

    # ---- Per-file renderers ----

    def _write_raw(self) -> None:
        lines = ["# Raw Highlights", ""]
        highlights = Highlight.objects.all().order_by("-highlighted_at", "-created_at")
        for i, h in enumerate(highlights, 1):
            lines.append(f"## Highlight {i}")
            lines.append(f"Text: {h.text}")
            if h.note:
                lines.append(f"Note: {h.note}")
            if h.source_title:
                source = h.source_title
                if h.source_author:
                    source += f" — {h.source_author}"
                lines.append(f"Source: {source}")
            if h.tags:
                lines.append(f"Tags: {', '.join(h.tags)}")
            lines.append(f"ReadwiseID: {h.readwise_id}")
            lines.append("")
        (self.raw_dir / "highlights.md").write_text("\n".join(lines))

    def _write_topic(self, topic: Topic) -> Path:
        path = self.wiki_dir / f"{topic.slug}.md"
        lines = [f"# {topic.name}", "", "## Overview"]
        lines.append(
            topic.summary or "_(summary pending — regenerates after enough new highlights)_"
        )
        lines.append("")
        lines.append("## Highlights")
        for h in topic.highlights.all().order_by("-highlighted_at"):
            source = f" — *{h.source_title}*" if h.source_title else ""
            text = h.text.replace("\n", " ").strip()
            lines.append(f'- "{text}"{source}')
        lines.append("")

        related = list(topic.related_topics.all().order_by("name"))
        if related:
            lines.append("## Related Topics")
            for r in related:
                # Standard Markdown link to peer file in wiki/ — clickable in any viewer.
                lines.append(f"- [{r.name}]({r.slug}.md)")
            lines.append("")

        path.write_text("\n".join(lines))
        return path

    def _write_index(self, topics: list[Topic]) -> None:
        lines = ["# My Knowledge Wiki", "", "## Topics"]
        if not topics:
            lines.append("_(no topics yet — run a sync)_")
        for t in topics:
            lines.append(f"- [{t.name}](wiki/{t.slug}.md)")
        lines.append("")
        lines.append("## Instructions for Agent")
        lines.append("See [CLAUDE.md](CLAUDE.md).")
        lines.append("")
        (self.output_dir / "index.md").write_text("\n".join(lines))


def _render_empty_index() -> str:
    return (
        "# My Knowledge Wiki\n\n"
        "## Topics\n_(no topics yet — run a sync)_\n\n"
        "## Instructions for Agent\nSee [CLAUDE.md](CLAUDE.md).\n"
    )
