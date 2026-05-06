"""`python manage.py sync_readwise [--async]` — run the full pipeline.

Default: run inline (foreground) so you can see what happened in your terminal.
With --async: enqueue the Celery chain and return immediately. Use this in CI or
when scripted; otherwise prefer the default for a clean local feedback loop.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from wiki.services.classifier import Classifier
from wiki.services.llm import LLMClient
from wiki.services.readwise import ReadwiseClient
from wiki.services.summarizer import Summarizer
from wiki.services.sync import sync_readwise
from wiki.services.writer import WikiWriter
from wiki.tasks import sync_readwise_task


class Command(BaseCommand):
    help = "Sync Readwise highlights, classify, summarize, and write the wiki."

    def add_arguments(self, parser):
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help="Enqueue via Celery instead of running inline.",
        )
        parser.add_argument(
            "--skip-llm",
            action="store_true",
            help="Sync + write only; skip classification and summarization (handy for testing the pipeline without spending tokens).",
        )

    def handle(self, *args, **options):
        if options["run_async"]:
            result = sync_readwise_task.delay()
            self.stdout.write(self.style.SUCCESS(f"Enqueued sync (task id: {result.id})"))
            return

        if not settings.READWISE_TOKEN:
            raise CommandError("READWISE_TOKEN is not set. Add it to .env first.")

        readwise = ReadwiseClient(token=settings.READWISE_TOKEN)
        sync_result = sync_readwise(readwise)
        self.stdout.write(
            f"Sync: fetched={sync_result.sync_run.fetched_count} "
            f"new={sync_result.sync_run.new_count}"
        )

        if not options["skip_llm"]:
            if not settings.LLM["API_KEY"] or not settings.LLM["MODEL"]:
                raise CommandError(
                    "LLM_API_KEY and LLM_MODEL must be set for classification. "
                    "Use --skip-llm to bypass."
                )
            llm = LLMClient(
                api_key=settings.LLM["API_KEY"],
                base_url=settings.LLM["BASE_URL"],
                model=settings.LLM["MODEL"],
            )
            classifier = Classifier(llm)
            outcomes = classifier.classify_pending()
            self.stdout.write(
                f"Classify: batches={len(outcomes)} "
                f"highlights={sum(len(o.classifications) for o in outcomes)}"
            )

            summarizer = Summarizer(llm)
            summary_outcomes = summarizer.summarize_pending()
            regenerated = sum(1 for o in summary_outcomes if not o.skipped)
            self.stdout.write(
                f"Summarize: total_topics={len(summary_outcomes)} regenerated={regenerated}"
            )

        writer = WikiWriter()
        writer.write_all()
        self.stdout.write(self.style.SUCCESS(f"Wiki written to {writer.output_dir}"))
