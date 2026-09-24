from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from threading import Lock
from time import monotonic


def rate_limit_identity(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


class FixedWindowRateLimiter:
    """Process-local rolling limiter used for local development and fallback."""

    def __init__(self, *, requests_per_minute: int) -> None:
        self._limit = max(requests_per_minute, 0)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def check(self, identity: str, *, now: float | None = None) -> tuple[bool, int, int]:
        if self._limit == 0:
            return True, 0, 0

        current = monotonic() if now is None else now
        cutoff = current - 60.0
        with self._lock:
            events = self._events[identity]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self._limit:
                retry_after = max(1, int(60.0 - (current - events[0])))
                return False, 0, retry_after

            events.append(current)
            remaining = max(self._limit - len(events), 0)
            return True, remaining, 0


class RedisWindowRateLimiter:
    """Shared fixed-minute limiter backed by Redis."""

    _SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

    def __init__(
        self,
        *,
        redis_url: str,
        requests_per_minute: int,
        namespace: str = "agrm:rate",
        client=None,
    ) -> None:
        self._limit = max(requests_per_minute, 0)
        self._namespace = namespace
        if client is None:
            from redis import Redis

            client = Redis.from_url(redis_url, decode_responses=True)
        self._client = client

    @property
    def limit(self) -> int:
        return self._limit

    def check(self, identity: str, *, now: float | None = None) -> tuple[bool, int, int]:
        if self._limit == 0:
            return True, 0, 0
        current = time.time() if now is None else now
        bucket = int(current // 60)
        key = f"{self._namespace}:{bucket}:{identity}"
        count, ttl = self._client.eval(self._SCRIPT, 1, key, 65)
        count = int(count)
        ttl = max(int(ttl), 1)
        remaining = max(self._limit - count, 0)
        return count <= self._limit, remaining, ttl


class ResilientRateLimiter:
    """Use shared Redis first, falling back to the local limiter on Redis errors."""

    def __init__(self, *, primary, fallback: FixedWindowRateLimiter) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def limit(self) -> int:
        return self._fallback.limit

    def check(self, identity: str) -> tuple[bool, int, int]:
        try:
            return self._primary.check(identity)
        except Exception:
            return self._fallback.check(identity)


def build_rate_limiter(
    *,
    requests_per_minute: int,
    redis_url: str | None = None,
):
    fallback = FixedWindowRateLimiter(
        requests_per_minute=requests_per_minute,
    )
    if not redis_url:
        return fallback
    return ResilientRateLimiter(
        primary=RedisWindowRateLimiter(
            redis_url=redis_url,
            requests_per_minute=requests_per_minute,
        ),
        fallback=fallback,
    )
