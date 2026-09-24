from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from amazon_geo_rank_monitor.domain.models import (
    ProbeStatus,
    RankObservation,
    RankSnapshot,
    VerificationLevel,
)
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


def repo() -> RankRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return RankRepository(engine)


def observation() -> RankObservation:
    return RankObservation(
        asin="B0TARGET01",
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
        status=ProbeStatus.SUCCESS_NOT_FOUND,
        found=False,
        organic_rank=None,
        absolute_rank=None,
        sponsored_rank=None,
        effective_rank=101,
    )


def test_persists_run_observation_and_snapshot() -> None:
    repository = repo()
    run_id = repository.create_run(
        marketplace="amazon.com", keyword="walking pad", requested_probe_count=1
    )
    repository.save_observations(run_id, [observation()])
    repository.save_snapshots(
        run_id,
        [
            RankSnapshot(
                asin="B0TARGET01",
                weighted_rank=Decimal("101.00"),
                found_weight=Decimal("0"),
                missing_weight=Decimal("100"),
                confidence=Decimal("0"),
            )
        ],
    )
    repository.complete_run(run_id, status="succeeded", settled_probe_count=1)

    saved = repository.get_run(run_id)
    assert saved["status"] == "succeeded"
    assert saved["observations"][0]["organic_rank"] is None
    assert saved["observations"][0]["effective_rank"] == 101
    assert saved["snapshots"][0]["weighted_rank"] == Decimal("101.00")


def test_duplicate_observation_identity_is_rejected() -> None:
    repository = repo()
    run_id = repository.create_run(
        marketplace="amazon.com", keyword="walking pad", requested_probe_count=1
    )
    repository.save_observations(run_id, [observation()])
    with pytest.raises(IntegrityError):
        repository.save_observations(run_id, [observation()])
