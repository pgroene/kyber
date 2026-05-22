from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, user_id: str, max_rpm: int) -> tuple[bool, int]:
        if max_rpm <= 0:
            return True, 0
        now = time.monotonic()
        window = [t for t in self._windows[user_id] if now - t < 60]
        self._windows[user_id] = window
        if len(window) >= max_rpm:
            age_of_oldest_request = now - window[0]
            retry_after = max(1, min(60, int(60 - age_of_oldest_request)))
            return False, retry_after
        return True, 0

    def record(self, user_id: str) -> None:
        self._windows[user_id].append(time.monotonic())


_rate_limiter = RateLimiter()
