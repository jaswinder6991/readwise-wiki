# Readwise → LLM Wiki

A pipeline that ingests highlights from [Readwise](https://readwise.io) and emits a Markdown wiki — agent-readable, human-readable,
and incrementally maintained.

> **What this is:** the data ingestion + structuring engine. The wiki itself is browsed in
> Wikiwise (or any agent IDE — Cursor, Claude Code). This system is a *compiler*, not a chatbot.

---

## What this demonstrates

End-to-end ownership of a Postgres-backed LLM pipeline:

- **Batched LLM classification** with JSON-mode responses, prompt design that keeps topic
  names canonical, and graceful handling of hallucinated refs.
- **`rapidfuzz`-based topic deduplication** so "Decision Making" / "Decision-making" /
  "Decisions" collapse to one canonical Topic before the wiki fragments.
- **A topic graph that emerges from classification consensus** — related-topic edges
  aggregated across calls, rendered as `[[Wikilinks]]`.
- **Threshold-gated topic-summary regeneration** — overviews only re-render once enough new
  evidence accumulates, saving tokens and keeping pages stable.
- **First-class LLM observability** — every call writes an `LLMCall` row (model, prompt /
  completion tokens, latency, batch FK, estimated USD), browsable in the Django admin.
- **Provider-agnostic LLM client** — OpenAI-compatible, points at OpenAI / OpenRouter /
  Together / vLLM by changing `LLM_BASE_URL`.
- **Production-shaped infrastructure** — Postgres, Celery + Redis (sync + classify +
  summarize + write run as separate, schedulable, retriable tasks), docker-compose, CI.

---

## Why this stack

The pipeline is fundamentally a fetch → classify → write-files loop. The choice of
Django + Postgres + Redis + Celery is deliberate:

- **Postgres + Django ORM** — the source of truth for highlights, topics, and the
  topic graph. The wiki Markdown is a regenerable view; the database holds the state.
- **Celery + Redis** — Readwise sync, batched LLM classification, and topic-summary
  regeneration each run as separate tasks so they can be scheduled (Beat), retried,
  observed, and scaled independently.
- **Django admin** — free inspection UI for highlights, topics, classification batches,
  and per-call LLM telemetry (token usage, latency, cost estimate).

Where the stack would be overkill (DRF, multiple Celery queues, custom admin, separate
read replicas, mypy on Django models), we deliberately don't go there. Each piece earns
its keep.

---

## Architecture

```
            ┌──────────────┐
            │  Readwise    │
            │  /export/    │
            └──────┬───────┘
                   │  pull (cursor pagination)
                   ▼
            ┌──────────────┐         ┌────────────────────┐
            │ Highlight DB │◄────────┤ Sync task (Celery) │
            └──────┬───────┘         └────────────────────┘
                   │
                   │  pending / unclassified
                   ▼
        ┌──────────────────────┐     ┌────────────────────┐
        │ Classifier service   │────►│  LLM (OpenAI-      │
        │  • batches (15)      │     │  compatible client)│
        │  • normalize + slug  │     └────────────────────┘
        │  • rapidfuzz dedup   │              │
        │  • topic graph edges │              │
        └──────────┬───────────┘              ▼
                   │                  ┌────────────────────┐
                   │                  │   LLMCall model    │
                   │                  │  (tokens, latency, │
                   │                  │   cost, batch FK)  │
                   │                  └────────────────────┘
                   ▼
        ┌──────────────────────┐
        │ Topic summary regen  │
        │  (threshold-gated)   │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │   Wiki writer        │  ──►  ./wiki-project/
        │  (full DB-driven     │       ├── index.md
        │   regen each sync)   │       ├── CLAUDE.md
        └──────────────────────┘       ├── raw/highlights.md
                                       └── wiki/{slug}.md
```

### Design points worth flagging

- **Database is the source of truth.** The Markdown wiki is regenerated from the DB on
  every sync — agent edits to `.md` files will be overwritten. Improvements should land
  in the DB (via Django admin or code). `CLAUDE.md` says this to the agent explicitly.
- **Topic dedup is non-trivial.** LLMs return "Decision Making" / "Decision-making" /
  "Decisions" interchangeably. The classifier normalizes → slugifies → fuzzy-matches via
  `rapidfuzz` against existing topics above a configurable threshold before creating a
  new one. Without this, the wiki fragments fast.
- **The topic graph emerges from classification consensus.** Each classification call
  returns related-topic suggestions per highlight; we aggregate those into symmetrical
  `Topic ↔ Topic` edges. The wiki's `[[Wikilinks]]` are populated from this graph.
- **LLM observability is first-class.** Every LLM call writes an `LLMCall` row
  (model, prompt/completion tokens, latency, batch FK, estimated USD). Browsable in
  the Django admin.
- **Topic summaries regenerate on a threshold,** not on every sync. Saves tokens and
  keeps summaries stable until enough new evidence accumulates
  (`SUMMARY_REGEN_THRESHOLD`).

---

## Quickstart

```bash
# 1. Bring up postgres + redis + django + celery worker + beat
cp .env.example .env   # then fill in READWISE_TOKEN, LLM_API_KEY, LLM_MODEL
docker compose up -d

# 2. (Optional) Create an admin user so you can browse highlights, topics, and
#    LLMCall telemetry at http://localhost:8000/admin/
docker compose exec web python manage.py createsuperuser

# 3. Initialize the wiki output directory
docker compose exec web python manage.py init_wiki

# 4. Sync highlights → classify → write wiki (runs inline)
docker compose exec web python manage.py sync_readwise

# Or run async via Celery:
docker compose exec web python manage.py sync_readwise --async
```

Output lands in `./wiki-project/` (configurable via `WIKI_OUTPUT_DIR`).

### Local (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# Bring up postgres + redis somehow (brew, colima, etc.)
python manage.py migrate
python manage.py init_wiki
python manage.py sync_readwise
```

---

## Tests

```bash
pytest                      # all tests
pytest tests/test_classifier.py -v
pytest --cov-report=html    # browse htmlcov/index.html
```

External services are mocked:
- Readwise HTTP via the [`responses`](https://github.com/getsentry/responses) library
- LLM responses via JSON fixtures injected into a `FakeLLMClient`

---

## Project layout

```
.
├── config/                      # Django + Celery wiring
│   ├── settings.py
│   ├── celery.py
│   └── urls.py
├── wiki/                        # the one Django app
│   ├── models.py                # Highlight, Topic, SyncRun, ClassificationBatch, LLMCall
│   ├── admin.py
│   ├── tasks.py                 # Celery tasks
│   ├── services/
│   │   ├── readwise.py          # /export/ client + pagination
│   │   ├── llm.py               # OpenAI-compatible client wrapper
│   │   ├── classifier.py        # batched classification + topic dedup
│   │   ├── summarizer.py        # threshold-gated topic summary regen
│   │   └── writer.py            # DB → Markdown wiki renderer
│   └── management/commands/
│       ├── init_wiki.py
│       └── sync_readwise.py
├── tests/
│   ├── conftest.py
│   ├── factories.py
│   ├── fixtures/
│   │   ├── readwise_export.json
│   │   └── llm_classification.json
│   └── test_*.py
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Configuration

All config is environment-driven (see `.env.example`). Key knobs:

| Var                            | Default                | What it does |
|--------------------------------|------------------------|--------------|
| `LLM_BASE_URL`                 | OpenRouter             | Any OpenAI-compatible endpoint |
| `LLM_MODEL`                    | *(unset, required)*    | e.g. `anthropic/claude-sonnet-4.6` |
| `WIKI_OUTPUT_DIR`              | `./wiki-project`       | Where the Markdown lands |
| `CLASSIFICATION_BATCH_SIZE`    | `15`                   | Highlights per LLM classification call |
| `SUMMARY_REGEN_THRESHOLD`      | `5`                    | New highlights needed before re-summarizing a topic |
| `TOPIC_FUZZY_MATCH_THRESHOLD`  | `88`                   | rapidfuzz score to merge near-duplicate topic names |

---
