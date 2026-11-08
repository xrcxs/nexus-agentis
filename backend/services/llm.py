"""Groq LLM client with exponential backoff + jitter, global rate limiter, and real token budget guard."""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx


class TokenBudgetExhaustedError(RuntimeError):
    """Raised before an LLM call when the run's token budget is exhausted."""


class LLMResponseError(RuntimeError):
    """Raised when the LLM API returns an unrecoverable error or invalid structure."""


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    latency_ms: float


class AsyncRateLimiter:
    """Global token-bucket rate limiter shared across concurrent runs."""

    def __init__(self, requests_per_minute: int = 30) -> None:
        self.rpm = max(1, requests_per_minute)
        self._min_interval = 60.0 / float(self.rpm)
        self._lock = asyncio.Lock()
        self._last_call_ts = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_ts
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_ts = time.monotonic()


def estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    """Conservative pre-call token estimate (~4 chars per token + message overhead)."""
    total_chars = sum(len(m.get("content", "")) + len(m.get("role", "")) for m in messages)
    return max(16, (total_chars // 4) + (len(messages) * 6))


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract a JSON object from raw LLM text or fenced markdown."""
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            cleaned = cleaned[first_brace : last_brace + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Expected top-level JSON object.")
    return parsed


class GroqLLMClient:
    """Async Groq OpenAI-compatible client with 429 retry/backoff and token accounting."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1",
        rate_limiter: AsyncRateLimiter | None = None,
        max_retries: int = 4,
        base_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        stub_Responder: Callable[[list[dict[str, str]], bool], dict[str, Any]] | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.rate_limiter = rate_limiter or AsyncRateLimiter(30)
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._transport = transport
        self._stub_responder = stub_Responder

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        current_tokens_used: int,
        token_budget: int,
        temperature: float = 0.1,
        max_completion_tokens: int = 1200,
        json_mode: bool = False,
    ) -> LLMCallResult:
        """Execute an LLM completion after checking the token budget guard."""
        estimated_prompt = estimate_prompt_tokens(messages)
        if current_tokens_used >= token_budget or (current_tokens_used + estimated_prompt) > token_budget:
            raise TokenBudgetExhaustedError(
                f"Token budget guard triggered: used={current_tokens_used}, "
                f"estimated_next_prompt={estimated_prompt}, budget_limit={token_budget}"
            )

        await self.rate_limiter.acquire()
        start_ts = time.perf_counter()

        if self._stub_responder is not None:
            raw_payload = self._stub_responder(messages, json_mode)
            latency_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
            return self._parse_openai_payload(raw_payload, latency_ms)

        if not self._api_key:
            raise LLMResponseError(
                "GROQ_API_KEY is not set. Provide GROQ_API_KEY in environment or enable NEXUS_STUB_APIS=true for offline fixtures."
            )

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_completion_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        async with httpx.AsyncClient(timeout=45.0, transport=self._transport) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        retry_after_hdr = resp.headers.get("retry-after")
                        if retry_after_hdr and retry_after_hdr.replace(".", "", 1).isdigit():
                            delay = float(retry_after_hdr)
                        else:
                            delay = self.base_backoff_seconds * (2**attempt)
                        jitter = random.uniform(0.0, 0.25 * delay + 0.05)
                        if attempt < self.max_retries:
                            await asyncio.sleep(delay + jitter)
                            continue
                        raise LLMResponseError(
                            f"Groq API HTTP {resp.status_code} after {self.max_retries + 1} attempts."
                        )

                    if resp.status_code >= 400:
                        raise LLMResponseError(
                            f"Groq API error HTTP {resp.status_code}: {resp.text[:300]}"
                        )

                    data = resp.json()
                    latency_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
                    return self._parse_openai_payload(data, latency_ms)
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    last_err = exc
                    if attempt < self.max_retries:
                        delay = self.base_backoff_seconds * (2**attempt) + random.uniform(0.01, 0.2)
                        await asyncio.sleep(delay)
                        continue
                    raise LLMResponseError(f"Groq network failure: {exc}") from exc

        raise LLMResponseError(f"Groq completion failed: {last_err}")

    def _parse_openai_payload(self, data: dict[str, Any], latency_ms: float) -> LLMCallResult:
        try:
            choices = data["choices"]
            content = str(choices[0]["message"]["content"])
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
            if total_tokens == 0 and content:
                prompt_tokens = max(1, len(content) // 4)
                completion_tokens = max(1, len(content) // 4)
                total_tokens = prompt_tokens + completion_tokens
            return LLMCallResult(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model=str(data.get("model", self.model)),
                latency_ms=latency_ms,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseError(f"Malformed Groq response payload: {exc}") from exc
