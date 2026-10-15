"""Small in-memory fixed-window limiter for the gateway.

Rate limiting is disabled unless GATEWAY_RATE_LIMIT is positive. It is deliberately local to
one gateway process; use an edge proxy or Redis-backed limiter for a distributed deployment.
"""
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int, now: float | None = None) -> int:
        """Return seconds to wait, or zero when the request fits in the rolling minute."""
        if limit <= 0:
            return 0
        now = time.monotonic() if now is None else now
        cutoff = now - 60
        with self._lock:
            for stale_key in [k for k, hits in self._buckets.items() if not hits or hits[-1] <= cutoff]:
                self._buckets.pop(stale_key, None)
            hits = self._buckets.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(hits[0] + 60 - now) + 1)
            hits.append(now)
            return 0


limiter = RateLimiter()
