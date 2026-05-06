"""Project-root conftest.

Loaded by pytest *before* pytest-django boots Django, so this is the right place to
override env vars for the test environment (use sqlite, set test secrets, etc.).
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_db.sqlite3")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("READWISE_TOKEN", "test-readwise-token")
