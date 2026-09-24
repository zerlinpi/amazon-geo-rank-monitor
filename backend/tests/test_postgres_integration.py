import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine

from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base

POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL is not configured",
)


def test_postgres_skip_locked_claims_distinct_jobs() -> None:
    engine = create_engine(POSTGRES_TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    jobs = JobRepository(engine)

    created = [
        jobs.enqueue(
            owner_id="tenant-a",
            provider_mode="managed",
            request_payload={"index": index},
        )
        for index in range(2)
    ]

    def claim():
        return JobRepository(engine).claim_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: claim(), range(2)))

    assert all(item is not None for item in claimed)
    claimed_ids = {item["id"] for item in claimed}
    assert claimed_ids == {item["id"] for item in created}
    assert all(item["status"] == "running" for item in claimed)
