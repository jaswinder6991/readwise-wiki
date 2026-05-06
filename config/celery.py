"""Celery application + beat schedule.

Three tasks compose the pipeline:
  1. sync_readwise_task        — pulls new highlights into the DB
  2. classify_pending_task     — batches unclassified highlights through the LLM
  3. summarize_pending_topics_task — re-summarizes topics past the threshold
  4. write_wiki_task           — renders the Markdown wiki from the DB

The beat schedule runs sync hourly; sync chains the rest on completion.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("readwise_wiki")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "sync-readwise-hourly": {
        "task": "wiki.tasks.sync_readwise_task",
        "schedule": crontab(minute=0),
    },
}
