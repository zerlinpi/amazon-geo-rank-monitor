import pytest
from sqlalchemy import create_engine

from amazon_geo_rank_monitor.domain.errors import InsufficientCreditsError
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import Base, TenantRow


def repository() -> BillingRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            TenantRow.__table__.insert().values(id="tenant-1", name="Tenant")
        )
    return BillingRepository(engine)


def test_grant_is_idempotent() -> None:
    repo = repository()
    first = repo.grant(
        owner_id="tenant-1", credits=100, idempotency_key="grant:1"
    )
    second = repo.grant(
        owner_id="tenant-1", credits=100, idempotency_key="grant:1"
    )
    assert first["balance"] == 100
    assert second["balance"] == 100
    assert len(repo.list_ledger(owner_id="tenant-1")) == 1


def test_reservation_reduces_available_not_balance() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=10, idempotency_key="grant:1")
    reservation = repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank:abc",
        reference_type="rank_check",
        reference_id="abc",
    )
    balance = repo.get_balance("tenant-1")
    assert reservation["amount"] == 5
    assert balance == {"balance": 10, "reserved": 5, "available": 5}


def test_duplicate_reservation_does_not_double_reserve() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=10, idempotency_key="grant:1")
    one = repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank:abc",
        reference_type="rank_check",
        reference_id="abc",
    )
    two = repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank:abc",
        reference_type="rank_check",
        reference_id="abc",
    )
    assert one["id"] == two["id"]
    assert repo.get_balance("tenant-1")["reserved"] == 5


def test_insufficient_available_credits_rejects_reservation() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=4, idempotency_key="grant:1")
    with pytest.raises(InsufficientCreditsError):
        repo.reserve(
            owner_id="tenant-1",
            credits=5,
            idempotency_key="rank:abc",
            reference_type="rank_check",
            reference_id="abc",
        )


def test_settle_charges_used_and_releases_unused() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=10, idempotency_key="grant:1")
    reservation = repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank:abc",
        reference_type="rank_check",
        reference_id="abc",
    )
    settled = repo.settle(reservation["id"], credits_used=3)
    assert settled["settled_amount"] == 3
    assert settled["released_amount"] == 2
    assert repo.get_balance("tenant-1") == {
        "balance": 7,
        "reserved": 0,
        "available": 7,
    }
    again = repo.settle(reservation["id"], credits_used=3)
    assert again["settled_amount"] == 3
    assert repo.get_balance("tenant-1")["balance"] == 7


def test_idempotency_key_cannot_cross_tenants() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            TenantRow.__table__.insert(),
            [
                {"id": "tenant-1", "name": "Tenant 1"},
                {"id": "tenant-2", "name": "Tenant 2"},
            ],
        )
    repo = BillingRepository(engine)
    repo.grant(owner_id="tenant-1", credits=10, idempotency_key="shared-key")
    with pytest.raises(ValueError, match="another tenant"):
        repo.grant(owner_id="tenant-2", credits=10, idempotency_key="shared-key")


def test_reservation_idempotency_requires_same_parameters() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=20, idempotency_key="grant:1")
    repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank:abc",
        reference_type="rank_check",
        reference_id="abc",
    )
    with pytest.raises(ValueError, match="different reservation parameters"):
        repo.reserve(
            owner_id="tenant-1",
            credits=6,
            idempotency_key="rank:abc",
            reference_type="rank_check",
            reference_id="abc",
        )


def test_release_by_idempotency_key_unlocks_stale_attempt_reservation() -> None:
    repo = repository()
    repo.grant(owner_id="tenant-1", credits=10, idempotency_key="grant:1")
    reservation = repo.reserve(
        owner_id="tenant-1",
        credits=5,
        idempotency_key="rank_job:job-1:attempt:1",
        reference_type="rank_job",
        reference_id="job-1",
    )

    released = repo.release_by_idempotency_key(
        "rank_job:job-1:attempt:1"
    )

    assert released["id"] == reservation["id"]
    assert released["status"] == "released"
    assert repo.get_balance("tenant-1") == {
        "balance": 10,
        "reserved": 0,
        "available": 10,
    }
    assert repo.release_by_idempotency_key("missing") is None
