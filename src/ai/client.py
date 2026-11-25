"""LLM client. Single provider: Pollinations (keyless, ~46s between requests)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class RateLimitError(Exception):
    pass


class ProviderError(Exception):
    pass


class AllProvidersFailed(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, max_tokens: int = 300) -> str:
        ...


class PollinationsProvider:
    """Anonymous free tier: ~1 request per 45 seconds per IP.

    The limit is per-IP, not per-client. Two DAGs firing on the same minute
    will collide — offset their schedules (brief at */15, explainer at
    :02,:07,:12,...).
    """

    name = "pollinations"
    ENDPOINT = "https://text.pollinations.ai/openai"
    MIN_SPACING_SEC = 46.0

    def __init__(self) -> None:
        self._last_call = 0.0

    def generate(self, prompt: str, max_tokens: int = 300) -> str:
        import requests

        elapsed = time.time() - self._last_call
        if elapsed < self.MIN_SPACING_SEC:
            time.sleep(self.MIN_SPACING_SEC - elapsed)

        try:
            resp = requests.post(
                self.ENDPOINT,
                json={
                    "model": "openai",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise ProviderError(str(exc)) from exc

        self._last_call = time.time()

        if resp.status_code in (402, 429):
            raise RateLimitError(resp.text)
        if resp.status_code >= 400:
            raise ProviderError(resp.text)

        data = resp.json()
        text = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not text:
            raise ProviderError("empty response")
        return text


class LLMClient:
    def __init__(self, providers: list[Provider] | None = None) -> None:
        self._providers = providers or [PollinationsProvider()]

    def generate(self, prompt: str, max_tokens: int = 300) -> LLMResult:
        errors: list[str] = []
        for p in self._providers:
            try:
                text = p.generate(prompt, max_tokens)
                return LLMResult(text=text, provider=p.name)
            except (RateLimitError, ProviderError) as exc:
                errors.append(f"{p.name}: {exc}")
        raise AllProvidersFailed("; ".join(errors))