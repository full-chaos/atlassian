from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable

from ..errors import LocalRateLimitError


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_rate_per_sec: float,
        now: Callable[[], datetime],
        sleeper: Callable[[float], None],
    ):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate_per_sec <= 0:
            raise ValueError("refill_rate_per_sec must be positive")
        self.capacity = float(capacity)
        self.refill_rate_per_sec = float(refill_rate_per_sec)
        self._tokens = float(capacity)
        self._now = now
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_refill = now()

    def _refill_locked(self, now: datetime) -> None:
        elapsed = (now - self._last_refill).total_seconds()
        if elapsed > 0:
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.refill_rate_per_sec,
            )
            self._last_refill = now

    def consume(self, cost: float, max_wait_seconds: float) -> float:
        """
        Consume tokens for the given estimated cost. Returns total wait time.
        Raises LocalRateLimitError if the wait would exceed max_wait_seconds.
        """
        if cost <= 0:
            return 0.0
        deadline = self._now() + timedelta(seconds=max_wait_seconds)
        waited = 0.0
        last_wait_needed = 0.0

        while True:
            now = self._now()
            with self._lock:
                self._refill_locked(now)
                if self._tokens >= cost:
                    self._tokens -= cost
                    return waited
                needed = cost - self._tokens
                last_wait_needed = needed / self.refill_rate_per_sec

            remaining = (deadline - self._now()).total_seconds()
            if remaining <= 0 or last_wait_needed <= 0:
                raise LocalRateLimitError(cost, last_wait_needed, max_wait_seconds)
            sleep_for = min(last_wait_needed, remaining)
            self._sleeper(sleep_for)
            waited += sleep_for
