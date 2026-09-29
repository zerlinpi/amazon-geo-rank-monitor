import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from test_run_history_pagination import seed_run

from amazon_geo_rank_monitor.domain.errors import CreditBudgetExceededError
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base, RankRunRow
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository

POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL is not configured",
)


def test_postgres_run_history_cursor_and_literal_keyword_filter() -> None:
    engine = create_engine(POSTGRES_TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ranks = RankRepository(engine)
    oldest = seed_run(ranks, "tenant-a", 1, keyword="100%_fit hitch")
    newest = seed_run(ranks, "tenant-a", 2, keyword="100%_fit hitch")
    seed_run(ranks, "tenant-a", 3, keyword="100XXfit hitch")
    seed_run(ranks, "tenant-b", 4, keyword="100%_fit hitch")
    page = ranks.list_run_page(owner_id="tenant-a", limit=1, keyword="%_FIT")
    assert [item["id"] for item in page["items"]] == [newest]
    page = ranks.list_run_page(
        owner_id="tenant-a", limit=1, keyword="%_FIT", cursor=page["next_cursor"],
    )
    assert [item["id"] for item in page["items"]] == [oldest]
    assert page["next_cursor"] is None


def test_postgres_history_time_bounds_are_normalized_to_utc() -> None:
    engine = create_engine(POSTGRES_TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ranks = RankRepository(engine)
    ids = [seed_run(ranks, "tenant-a", i) for i in range(1, 5)]
    with ranks._sessions.begin() as session:
        for hour, run_id in enumerate(ids):
            session.get(RankRunRow, run_id).started_at = datetime(
                2026, 9, 28, hour, tzinfo=UTC,
            )
    page = ranks.list_run_page(
        owner_id="tenant-a",
        started_from=datetime(2026, 9, 28, 9, tzinfo=timezone(timedelta(hours=8))),
        started_until=datetime(2026, 9, 27, 22, tzinfo=timezone(timedelta(hours=-4))),
    )
    assert [item["id"] for item in page["items"]] == [ids[2], ids[1]]
    assert page["next_cursor"] is None
    assert all(item["started_at"].utcoffset() == timedelta(0) for item in page["items"])


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
