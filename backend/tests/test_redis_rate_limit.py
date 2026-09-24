import os

import pytest
from redis import Redis

from amazon_geo_rank_monitor.api.rate_limit import (
    RedisWindowRateLimiter,
    rate_limit_identity,
)

REDIS_TEST_URL = os.getenv("REDIS_TEST_URL")

pytestmark = pytest.mark.skipif(
    not REDIS_TEST_URL,
    reason="REDIS_TEST_URL is not configured",
)


def test_redis_rate_limit_is_shared_across_instances() -> None:
    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    client.flushdb()
    one = RedisWindowRateLimiter(
        redis_url=REDIS_TEST_URL,
        requests_per_minute=2,
        client=client,
    )
    two = RedisWindowRateLimiter(
        redis_url=REDIS_TEST_URL,
        requests_per_minute=2,
        client=client,
    )
    identity = rate_limit_identity("agrm_secret-value")

    assert one.check(identity)[0] is True
    assert two.check(identity)[0] is True
    allowed, remaining, retry_after = one.check(identity)

    assert allowed is False
    assert remaining == 0
    assert retry_after >= 1
    keys = client.keys("agrm:rate:*")
    assert keys
    assert all("agrm_secret-value" not in key for key in keys)


def test_rate_limit_identity_never_contains_plaintext_key() -> None:
    plaintext = "agrm_super-secret"
    identity = rate_limit_identity(plaintext)

    assert identity != plaintext
    assert plaintext not in identity
    assert len(identity) == 64
