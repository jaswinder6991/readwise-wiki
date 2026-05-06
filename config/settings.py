"""Django settings for the Readwise → Wiki project.

Single-file settings on purpose: small project, env-driven via django-environ.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CLASSIFICATION_BATCH_SIZE=(int, 15),
    SUMMARY_REGEN_THRESHOLD=(int, 5),
    TOPIC_FUZZY_MATCH_THRESHOLD=(int, 88),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-secret-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wiki",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        # Default to sqlite so tests and first-run "git clone && pip install" Just Work
        # without a running Postgres. docker-compose and the .env template override this
        # to postgres for real use.
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR}/db.sqlite3",
    ),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- App-specific config ---

READWISE_TOKEN = env("READWISE_TOKEN", default="")

LLM = {
    "API_KEY": env("LLM_API_KEY", default=""),
    "BASE_URL": env("LLM_BASE_URL", default="https://openrouter.ai/api/v1"),
    "MODEL": env("LLM_MODEL", default=""),
}

WIKI = {
    "OUTPUT_DIR": Path(env("WIKI_OUTPUT_DIR", default=str(BASE_DIR / "wiki-project"))),
    "CLASSIFICATION_BATCH_SIZE": env("CLASSIFICATION_BATCH_SIZE"),
    "SUMMARY_REGEN_THRESHOLD": env("SUMMARY_REGEN_THRESHOLD"),
    "TOPIC_FUZZY_MATCH_THRESHOLD": env("TOPIC_FUZZY_MATCH_THRESHOLD"),
}

# --- Celery ---

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
