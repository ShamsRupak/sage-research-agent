"""
SAGE LLM Client — provider-agnostic wrapper around LLM APIs.

Supports Groq (primary) and Google Gemini (fallback).
Handles retries, error recovery, token tracking, and rate limiting.
No agent logic lives here — this is a pure communication layer.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMResponse:
    """Structured response from an LLM call."""
    content: str
    model: str
    tokens_used: int = 0
    latency_seconds: float = 0.0
    provider: str = "unknown"
    raw_response: object = None


@dataclass
class TokenTracker:
    """Tracks cumulative token usage across all calls."""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_calls: int = 0
    failed_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def record(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_calls += 1

    def record_failure(self) -> None:
        self.failed_calls += 1

    def summary(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }


class LLMClient:
    """
    Provider-agnostic LLM client with automatic fallback.

    Primary: Groq API (llama-3.3-70b-versatile)
    Fallback: Google Gemini 1.5 Flash

    Usage:
        client = LLMClient()
        response = await client.complete("What is X?")
    """

    def __init__(
        self,
        groq_api_key: str | None = None,
        gemini_api_key: str | None = None,
        primary_model: str = "llama-3.3-70b-versatile",
        fallback_model: str = "gemini-1.5-flash",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.tracker = TokenTracker()

        # Lazy-initialized clients
        self._groq_client = None
        self._gemini_model = None

    def _get_groq_client(self):
        """Lazy-init Groq client."""
        if self._groq_client is None:
            from groq import Groq
            self._groq_client = Groq(api_key=self.groq_api_key)
        return self._groq_client

    def _get_gemini_model(self):
        """Lazy-init Gemini model."""
        if self._gemini_model is None:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_model = genai.GenerativeModel(self.fallback_model)
        return self._gemini_model

    async def complete(
        self,
        prompt: str,
        system: str = "You are a helpful research assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Send a completion request. Tries Groq first, falls back to Gemini.
        Returns the response content as a string.
        """
        response = await self._complete_with_metadata(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content

    async def _complete_with_metadata(
        self,
        prompt: str,
        system: str = "You are a helpful research assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Full completion with metadata tracking.
        Tries primary provider, then fallback on failure.
        """
        # Try Groq first
        if self.groq_api_key:
            for attempt in range(self.max_retries):
                try:
                    return await self._call_groq(
                        prompt, system, temperature, max_tokens
                    )
                except Exception as e:
                    self.tracker.record_failure()
                    if attempt < self.max_retries - 1:
                        wait = self.retry_delay * (2 ** attempt)
                        await asyncio.sleep(wait)
                    else:
                        # Fall through to Gemini
                        break

        # Try Gemini fallback
        if self.gemini_api_key:
            for attempt in range(self.max_retries):
                try:
                    return await self._call_gemini(
                        prompt, system, temperature, max_tokens
                    )
                except Exception as e:
                    self.tracker.record_failure()
                    if attempt < self.max_retries - 1:
                        wait = self.retry_delay * (2 ** attempt)
                        await asyncio.sleep(wait)
                    else:
                        raise RuntimeError(
                            f"All LLM providers failed. Last error: {e}"
                        ) from e

        raise RuntimeError(
            "No LLM API keys configured. Set GROQ_API_KEY or GEMINI_API_KEY in .env"
        )

    async def _call_groq(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call Groq API (synchronous SDK, wrapped in asyncio executor)."""
        client = self._get_groq_client()

        def _sync_call():
            return client.chat.completions.create(
                model=self.primary_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

        start = time.time()
        response = await asyncio.get_event_loop().run_in_executor(
            None, _sync_call
        )
        latency = time.time() - start

        content = response.choices[0].message.content or ""
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
        completion_tokens = getattr(response.usage, "completion_tokens", 0)

        self.tracker.record(prompt_tokens, completion_tokens)

        return LLMResponse(
            content=content,
            model=self.primary_model,
            tokens_used=prompt_tokens + completion_tokens,
            latency_seconds=round(latency, 3),
            provider="groq",
            raw_response=response,
        )

    async def _call_gemini(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call Google Gemini API."""
        model = self._get_gemini_model()
        full_prompt = f"{system}\n\n{prompt}"

        def _sync_call():
            return model.generate_content(
                full_prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )

        start = time.time()
        response = await asyncio.get_event_loop().run_in_executor(
            None, _sync_call
        )
        latency = time.time() - start

        content = response.text or ""
        # Gemini doesn't always expose token counts in the same way
        token_estimate = len(full_prompt.split()) + len(content.split())

        self.tracker.record(
            prompt_tokens=len(full_prompt.split()),
            completion_tokens=len(content.split()),
        )

        return LLMResponse(
            content=content,
            model=self.fallback_model,
            tokens_used=token_estimate,
            latency_seconds=round(latency, 3),
            provider="gemini",
            raw_response=response,
        )

    def get_usage_summary(self) -> dict:
        """Return cumulative usage stats."""
        return self.tracker.summary()