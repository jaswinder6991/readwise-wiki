"""OpenAI-compatible LLM client wrapper.

Targets the `openai` SDK in chat-completions mode against any OpenAI-compatible
endpoint (OpenAI, OpenRouter, Together, vLLM, etc.) — `base_url` and `api_key`
are configurable via env (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).

The wrapper is intentionally thin. Its job is:
  1. Make the call.
  2. Parse JSON out of the response.
  3. Return token counts + latency for telemetry.

Caller decides what to do with the result and how to persist the LLMCall row.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from openai import OpenAI

from wiki.services.pricing import estimate_cost_usd


@dataclass(frozen=True)
class LLMResult:
    """What every LLM call returns: parsed payload + measurable telemetry."""

    payload: Any
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cost_estimate_usd: Decimal


class LLMClientProtocol(Protocol):
    """Anything the classifier/summarizer needs from an LLM. Lets tests inject a fake."""

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> LLMResult: ...


class LLMClient:
    """OpenAI-compatible chat-completions client returning parsed JSON."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        model: str | None = None,
        client: OpenAI | None = None,
    ):
        if not api_key and client is None:
            raise ValueError("LLM_API_KEY is required")
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)
        self._default_model = model

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> LLMResult:
        model_name = model or self._default_model
        if not model_name:
            raise ValueError(
                "LLM model is not configured. Set LLM_MODEL or pass model= explicitly."
            )

        started = time.monotonic()
        response = self._client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = (
            getattr(usage, "total_tokens", prompt_tokens + completion_tokens) if usage else 0
        )

        return LLMResult(
            payload=payload,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_estimate_usd=estimate_cost_usd(model_name, prompt_tokens, completion_tokens),
        )
