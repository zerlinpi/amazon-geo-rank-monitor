from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class FixedWindowRateLimiter:
    """Small in-process limiter for API keys.

    Production deployments with multiple API replicas should enforce an additional
    shared limit at the gateway or replace this implementation with a shared store.
    """

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
