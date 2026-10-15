import unittest

from app.rate_limit import RateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_disabled_limit_never_blocks(self):
        limiter = RateLimiter()
        self.assertEqual(limiter.check("client", 0, now=0), 0)
        self.assertEqual(limiter.check("client", 0, now=0), 0)

    def test_allows_the_limit_then_returns_a_retry_delay(self):
        limiter = RateLimiter()
        self.assertEqual(limiter.check("client", 2, now=10), 0)
        self.assertEqual(limiter.check("client", 2, now=20), 0)
        self.assertEqual(limiter.check("client", 2, now=30), 41)

    def test_expired_hits_are_not_counted(self):
        limiter = RateLimiter()
        limiter.check("client", 1, now=10)
        self.assertEqual(limiter.check("client", 1, now=70), 0)

    def test_clients_have_separate_buckets(self):
        limiter = RateLimiter()
        limiter.check("one", 1, now=10)
        self.assertEqual(limiter.check("two", 1, now=10), 0)


if __name__ == "__main__":
    unittest.main()
