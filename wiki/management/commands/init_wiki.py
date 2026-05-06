"""`python manage.py init_wiki` — create the output dir skeleton + CLAUDE.md."""

from django.core.management.base import BaseCommand

from wiki.services.writer import WikiWriter


class Command(BaseCommand):
    help = "Create the Wikiwise-compatible output directory skeleton."

    def handle(self, *args, **options):
        writer = WikiWriter()
        writer.init_skeleton()
        self.stdout.write(self.style.SUCCESS(f"Initialized wiki skeleton at {writer.output_dir}"))
