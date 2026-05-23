from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check_and_record(self, user_id: str, max_rpm: int) -> tuple[bool, int]:
        """Atomically check the rate limit and record the request if allowed.

        Returns (allowed, retry_after_seconds).
        """
        if max_rpm <= 0:
            return True, 0
        now = time.monotonic()
        window = [t for t in self._windows[user_id] if now - t < 60]
        if len(window) >= max_rpm:
            retry_after = int(60 - (now - window[0])) + 1
            self._windows[user_id] = window
            return False, retry_after
        window.append(now)
        self._windows[user_id] = window
        return True, 0


_rate_limiter = RateLimiter()
