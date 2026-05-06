"""factory_boy factories for test setup."""

from __future__ import annotations

import factory
from django.utils import timezone
from django.utils.text import slugify

from wiki.models import ClassificationBatch, Highlight, LLMCall, SyncRun, Topic


class TopicFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Topic
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Topic {n}")
    slug = factory.LazyAttribute(lambda o: slugify(o.name))
    summary = ""


class HighlightFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Highlight

    readwise_id = factory.Sequence(lambda n: 10_000 + n)
    text = factory.Faker("sentence", nb_words=12)
    source_title = factory.Faker("sentence", nb_words=4)
    source_author = factory.Faker("name")
    source_url = factory.Faker("url")
    tags = factory.LazyFunction(list)
    highlighted_at = factory.LazyFunction(timezone.now)


class SyncRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SyncRun


class ClassificationBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClassificationBatch


class LLMCallFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LLMCall

    purpose = LLMCall.PURPOSE_CLASSIFY
    model_name = "test-model"
    prompt_tokens = 100
    completion_tokens = 50
    total_tokens = 150
    latency_ms = 200
