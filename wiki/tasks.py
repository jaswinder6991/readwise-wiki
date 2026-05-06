"""Celery tasks composing the pipeline.

The orchestration is intentionally simple: `sync_readwise_task` chains the rest on
completion, so triggering one task triggers the whole pipeline. Beat runs the chain
hourly; ad-hoc invocations work the same way.
"""

from __future__ import annotations

import logging

from celery import chain, shared_task
from django.conf import settings

from wiki.services.classifier import Classifier
from wiki.services.llm import LLMClient
from wiki.services.readwise import ReadwiseClient
from wiki.services.summarizer import Summarizer
from wiki.services.sync import sync_readwise
from wiki.services.writer import WikiWriter

logger = logging.getLogger(__name__)


def _build_llm_client() -> LLMClient:
    return LLMClient(
        api_key=settings.LLM["API_KEY"],
        base_url=settings.LLM["BASE_URL"],
        model=settings.LLM["MODEL"],
    )


def _build_readwise_client() -> ReadwiseClient:
    return ReadwiseClient(token=settings.READWISE_TOKEN)


@shared_task(name="wiki.tasks.sync_readwise_task")
def sync_readwise_task() -> dict:
    """Pull new highlights from Readwise and chain classify → summarize → write."""
    result = sync_readwise(_build_readwise_client())
    logger.info(
        "sync_readwise: fetched=%s new=%s",
        result.sync_run.fetched_count,
        result.sync_run.new_count,
    )
    chain(
        classify_pending_task.si(),
        summarize_pending_topics_task.si(),
        write_wiki_task.si(),
    ).apply_async()
    return {
        "sync_run_id": result.sync_run.id,
        "fetched": result.sync_run.fetched_count,
        "new": result.sync_run.new_count,
    }


@shared_task(name="wiki.tasks.classify_pending_task")
def classify_pending_task() -> dict:
    classifier = Classifier(_build_llm_client())
    outcomes = classifier.classify_pending()
    logger.info("classify_pending: batches=%s", len(outcomes))
    return {
        "batches": len(outcomes),
        "highlights": sum(len(o.classifications) for o in outcomes),
    }


@shared_task(name="wiki.tasks.summarize_pending_topics_task")
def summarize_pending_topics_task() -> dict:
    summarizer = Summarizer(_build_llm_client())
    outcomes = summarizer.summarize_pending()
    regenerated = sum(1 for o in outcomes if not o.skipped)
    logger.info("summarize_pending: total_topics=%s regenerated=%s", len(outcomes), regenerated)
    return {"total_topics": len(outcomes), "regenerated": regenerated}


@shared_task(name="wiki.tasks.write_wiki_task")
def write_wiki_task() -> dict:
    writer = WikiWriter()
    writer.write_all()
    logger.info("write_wiki: output_dir=%s", writer.output_dir)
    return {"output_dir": str(writer.output_dir)}
