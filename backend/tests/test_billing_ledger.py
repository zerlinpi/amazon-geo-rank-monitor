from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.billing.errors import InsufficientCreditsError
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import Base


def repository() -> BillingRepository:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return BillingRepository(engine)


def test_grant_is_idempotent() -> None:
    billing = repository()

    first = billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )
    second = billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )

    assert first["available_credits"] == 10
    assert second["available_credits"] == 10
    assert len(billing.list_ledger(owner_id="tenant-a")) == 1


def test_reserve_then_partial_settle_releases_unused_credits() -> None:
    billing = repository()
    billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )

    reservation = billing.reserve(
        owner_id="tenant-a",
        amount=5,
        idempotency_key="reserve-job-1",
        reference_type="rank_job",
        reference_id="job-1",
    )
    held = billing.get_account("tenant-a")
    assert held["available_credits"] == 5
    assert held["reserved_credits"] == 5

    settled = billing.settle(
        reservation["id"],
        actual_amount=4,
        idempotency_key="settle-job-1",
    )
    account = billing.get_account("tenant-a")

    assert settled["status"] == "settled"
    assert settled["settled_amount"] == 4
    assert settled["released_amount"] == 1
    assert account["available_credits"] == 6
    assert account["reserved_credits"] == 0


def test_settlement_is_idempotent() -> None:
    billing = repository()
    billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )
    reservation = billing.reserve(
        owner_id="tenant-a",
        amount=5,
        idempotency_key="reserve-job-1",
        reference_type="rank_job",
        reference_id="job-1",
    )

    billing.settle(
        reservation["id"],
        actual_amount=4,
        idempotency_key="settle-job-1",
    )
    billing.settle(
        reservation["id"],
        actual_amount=4,
        idempotency_key="settle-job-1",
    )

    account = billing.get_account("tenant-a")
    assert account["available_credits"] == 6
    assert account["reserved_credits"] == 0


def test_release_restores_full_reservation() -> None:
    billing = repository()
    billing.grant(
        owner_id="tenant-a",
        amount=8,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )
    reservation = billing.reserve(
        owner_id="tenant-a",
        amount=5,
        idempotency_key="reserve-job-1",
        reference_type="rank_job",
        reference_id="job-1",
    )

    released = billing.release(
        reservation["id"],
        idempotency_key="release-job-1",
    )
    account = billing.get_account("tenant-a")

    assert released["status"] == "released"
    assert released["settled_amount"] == 0
    assert released["released_amount"] == 5
    assert account["available_credits"] == 8
    assert account["reserved_credits"] == 0


def test_insufficient_credits_does_not_create_reservation() -> None:
    billing = repository()
    billing.grant(
        owner_id="tenant-a",
        amount=2,
        idempotency_key="grant-1",
        reference_type="test",
        reference_id="seed",
    )

    try:
        billing.reserve(
            owner_id="tenant-a",
            amount=3,
            idempotency_key="reserve-job-1",
            reference_type="rank_job",
            reference_id="job-1",
        )
    except InsufficientCreditsError as exc:
        assert exc.available == 2
        assert exc.required == 3
    else:
        raise AssertionError("expected InsufficientCreditsError")

    account = billing.get_account("tenant-a")
    assert account["available_credits"] == 2
    assert account["reserved_credits"] == 0


def test_accounts_and_ledger_are_tenant_scoped() -> None:
    billing = repository()
    billing.grant(
        owner_id="tenant-a",
        amount=5,
        idempotency_key="grant-a",
        reference_type="test",
        reference_id="a",
    )
    billing.grant(
        owner_id="tenant-b",
        amount=7,
        idempotency_key="grant-b",
        reference_type="test",
        reference_id="b",
    )

    assert billing.get_account("tenant-a")["available_credits"] == 5
    assert billing.get_account("tenant-b")["available_credits"] == 7
    assert {e["owner_id"] for e in billing.list_ledger(owner_id="tenant-a")} == {
        "tenant-a"
    }
