"""Redis brief cache. The API reads here; the DAG writes here."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import redis


def _client() -> redis.Redis:
    return redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )


BRIEF_KEY = "aeropulse:brief:latest"
BRIEF_TTL_SEC = 1200  


def set_brief(text: str, provider: str) -> None:
    payload = {
        "text": text,
        "provider": provider,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _client().set(BRIEF_KEY, json.dumps(payload), ex=BRIEF_TTL_SEC)


def get_brief() -> dict | None:
    raw = _client().get(BRIEF_KEY)
    if raw is None:
        return None
    return json.loads(raw)