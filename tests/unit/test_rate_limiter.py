from __future__ import annotations

import time

from voxagent.server.middleware import RateLimiter


class TestRateLimiter:
    def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(limit=5, window_seconds=60)
        for _ in range(5):
            assert limiter.is_allowed("client1")

    def test_blocks_requests_over_limit(self) -> None:
        limiter = RateLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.is_allowed("client1")
        assert not limiter.is_allowed("client1")

    def test_different_keys_independent(self) -> None:
        limiter = RateLimiter(limit=2, window_seconds=60)
        limiter.is_allowed("a")
        limiter.is_allowed("a")
        assert not limiter.is_allowed("a")
        assert limiter.is_allowed("b")

    def test_window_expiry(self) -> None:
        # Use a 1-second window; after it expires the counter resets
        limiter = RateLimiter(limit=2, window_seconds=1)
        assert limiter.is_allowed("client1")
        assert limiter.is_allowed("client1")
        assert not limiter.is_allowed("client1")

        # Wait for the window to expire
        time.sleep(1.1)

        # Requests should be allowed again
        assert limiter.is_allowed("client1")

    def test_first_request_always_allowed(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        assert limiter.is_allowed("new_key")

    def test_limit_of_one_blocks_second_request(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        limiter.is_allowed("client1")
        assert not limiter.is_allowed("client1")

    def test_many_independent_keys(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        for i in range(100):
            assert limiter.is_allowed(f"client{i}")
