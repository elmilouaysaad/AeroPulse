import pytest

from src.ai.client import (
    LLMClient, ProviderError, RateLimitError, AllProvidersFailed,
)


class FakeProvider:
    def __init__(self, name, behaviour):
        self.name = name
        self._behaviour = behaviour
        self.calls = 0

    def generate(self, prompt, max_tokens=300):
        self.calls += 1
        if self._behaviour == "ok":
            return f"{self.name}-response"
        if self._behaviour == "rate":
            raise RateLimitError("429")
        raise ProviderError("500")


def test_falls_back_on_rate_limit():
    a = FakeProvider("a", "rate")
    b = FakeProvider("b", "ok")
    result = LLMClient(providers=[a, b]).generate("hi")
    assert result.text == "b-response"
    assert result.provider == "b"


def test_falls_back_on_provider_error():
    a = FakeProvider("a", "err")
    b = FakeProvider("b", "ok")
    result = LLMClient(providers=[a, b]).generate("hi")
    assert result.provider == "b"


def test_raises_when_all_fail():
    a = FakeProvider("a", "err")
    b = FakeProvider("b", "rate")
    with pytest.raises(AllProvidersFailed):
        LLMClient(providers=[a, b]).generate("hi")


def test_primary_wins_when_healthy():
    a = FakeProvider("a", "ok")
    b = FakeProvider("b", "ok")
    result = LLMClient(providers=[a, b]).generate("hi")
    assert result.provider == "a"
    assert b.calls == 0