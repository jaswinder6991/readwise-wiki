FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Copy source before installing the project so setuptools' package discovery sees
# `config/` and `wiki/` at install time. (Splitting deps from the editable install
# would let us cache the deps layer, but that's premature optimization for a project
# this size — correctness wins.)
COPY . .
RUN pip install -e ".[dev]"

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
