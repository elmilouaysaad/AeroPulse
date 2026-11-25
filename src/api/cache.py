"""Redis cache reads for the API."""
from __future__ import annotations

import json
import os

import redis


def _client() -> redis.Redis:
    return redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )


BRIEF_KEY = "aeropulse:brief:latest"


def cached_brief() -> dict | None:
    raw = _client().get(BRIEF_KEY)
    if raw is None:
        return None
    return json.loads(raw)