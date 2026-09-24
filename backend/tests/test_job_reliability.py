from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError
from amazon_geo_rank_monitor.domain.models import GeoProfile, RankCheckRequest
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


def build_jobs(*, max_attempts: int = 3) -> JobRepository:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return JobRepository(engine, default_max_attempts=max_attempts)


def test_retry_backoff_then_dead_letter_and_manual_requeue() -> None:
    jobs = build_jobs(max_attempts=2)
    now = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload={"keyword": "walking pad"},
        available_at=now,
    )

    first = jobs.claim_one(worker_id="worker-a", lease_seconds=30, now=now)
    assert first["id"] == created["id"]
    assert first["attempt_count"] == 1
    assert first["claimed_by"] == "worker-a"

    retry = jobs.retry_or_dead_letter(
        created["id"],
        error="provider timeout",
        base_delay_seconds=5,
        max_delay_seconds=60,
        now=now,
    )
    assert retry["status"] == "pending"
    assert retry["attempt_count"] == 1

    assert jobs.claim_one(
        worker_id="worker-b",
        lease_seconds=30,
        now=now + timedelta(seconds=4),
    ) is None

    second = jobs.claim_one(
        worker_id="worker-b",
        lease_seconds=30,
        now=now + timedelta(seconds=5),
    )
    assert second["attempt_count"] == 2
    assert second["claimed_by"] == "worker-b"

    dead = jobs.retry_or_dead_letter(
        created["id"],
        error="provider timeout again",
        base_delay_seconds=5,
        max_delay_seconds=60,
        now=now + timedelta(seconds=5),
    )
    assert dead["status"] == "dead_letter"
    assert dead["attempt_count"] == 2
    assert jobs.list_dead_letters()[0]["id"] == created["id"]

    requeued = jobs.requeue_dead_letter(
        created["id"],
        now=now + timedelta(seconds=10),
    )
    assert requeued["status"] == "pending"
    assert requeued["attempt_count"] == 0
    assert requeued["error"] is None


def test_stale_leases_are_retried_then_dead_lettered() -> None:
    jobs = build_jobs(max_attempts=2)
    now = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload={},
        available_at=now,
    )

    jobs.claim_one(worker_id="worker-a", lease_seconds=10, now=now)
    first_recovery = jobs.recover_stale(now=now + timedelta(seconds=11))

    assert first_recovery["retried"] == 1
    assert first_recovery["dead_lettered"] == 0
    assert first_recovery["recovered_attempts"] == [
        {"job_id": created["id"], "attempt_count": 1}
    ]

    jobs.claim_one(
        worker_id="worker-b",
        lease_seconds=10,
        now=now + timedelta(seconds=11),
    )
    second_recovery = jobs.recover_stale(now=now + timedelta(seconds=22))

    assert second_recovery["retried"] == 0
    assert second_recovery["dead_lettered"] == 1
    assert jobs.get(created["id"], owner_id="tenant-a")["status"] == "dead_letter"


def test_renewed_lease_is_not_recovered_early() -> None:
    jobs = build_jobs()
    now = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload={},
        available_at=now,
    )
    jobs.claim_one(worker_id="worker-a", lease_seconds=10, now=now)

    assert jobs.renew_lease(
        created["id"],
        worker_id="worker-a",
        lease_seconds=10,
        now=now + timedelta(seconds=5),
    )
    assert jobs.recover_stale(now=now + timedelta(seconds=11))["retried"] == 0
    assert jobs.recover_stale(now=now + timedelta(seconds=16))["retried"] == 1


def test_queue_summary_counts_dead_letters() -> None:
    jobs = build_jobs(max_attempts=1)
    now = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload={},
        available_at=now,
    )
    jobs.claim_one(worker_id="worker-a", lease_seconds=10, now=now)
    jobs.retry_or_dead_letter(
        created["id"],
        error="fatal",
        now=now,
    )

    summary = jobs.queue_summary()
    assert summary["counts"]["dead_letter"] == 1


class FailingProvider:
    provider_name = "failing"

    async def search(self, **kwargs):
        raise ProviderUnavailableError("provider temporarily unavailable")


async def test_worker_retries_total_provider_failure_then_dead_letters() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    jobs = JobRepository(engine, default_max_attempts=2)
    request = RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profiles=[
            GeoProfile(
                id="ny",
                name="New York",
                marketplace="amazon.com",
                ip_country="US",
                delivery_country="US",
                delivery_postal_code="10001",
                weight=Decimal("100"),
            )
        ],
        search_depth=100,
    )
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request.model_dump(mode="json"),
    )
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=RankRepository(engine),
        provider_registry=ProviderRegistry(
            managed=FailingProvider(),
            strict=FailingProvider(),
        ),
        worker_id="worker-a",
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    first = await worker.run_once()
    assert first["status"] == "pending"
    assert first["attempt_count"] == 1

    second = await worker.run_once()
    assert second["status"] == "dead_letter"
    assert second["attempt_count"] == 2
    assert second["id"] == created["id"]
