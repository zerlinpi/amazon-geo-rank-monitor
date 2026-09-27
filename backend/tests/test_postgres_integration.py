import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from amazon_geo_rank_monitor.domain.errors import CreditBudgetExceededError
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository

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


def test_postgres_daily_strict_budget_is_atomic_across_workers() -> None:
    engine = create_engine(POSTGRES_TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    tenant = tenants.create_tenant("Budget Tenant")
    billing = BillingRepository(engine)
    billing.grant(
        owner_id=tenant["id"],
        credits=20,
        idempotency_key="grant:postgres-budget",
    )
    window_start = datetime.now(UTC).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    def reserve(index: int) -> str:
        try:
            BillingRepository(engine).reserve(
                owner_id=tenant["id"],
                credits=5,
                idempotency_key=f"strict:postgres:{index}",
                reference_type="auto_strict_verification",
                reference_id=f"run-{index}",
                reference_budget_limit=5,
                reference_budget_window_start=window_start,
            )
            return "reserved"
        except CreditBudgetExceededError:
            return "budget_exceeded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))

    assert sorted(outcomes) == ["budget_exceeded", "reserved"]
    assert billing.get_balance(tenant["id"]) == {
        "balance": 20,
        "reserved": 5,
        "available": 15,
    }
