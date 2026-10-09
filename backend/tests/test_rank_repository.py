from datetime import UTC, datetime, timedelta
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


def test_verification_analytics_breaks_down_effectiveness_and_reasons() -> None:
    repository = repo()

    cached_run = repository.create_run(
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    repository.complete_run(
        cached_run,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "strict_requested_count": 1,
            "strict_attempted_count": 0,
            "strict_succeeded_count": 1,
            "strict_skipped_count": 0,
            "events": [
                {
                    "geo_profile_id": "ny",
                    "requested": True,
                    "attempted": False,
                    "succeeded": True,
                    "cache_hit": True,
                    "triggers": ["rank_movement:B0TARGET01:25"],
                    "skipped_reason": None,
                    "error": None,
                }
            ],
        },
    )

    recovered_run = repository.create_run(
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    repository.complete_run(
        recovered_run,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "manual_force_requested": True,
            "strict_requested_count": 1,
            "strict_attempted_count": 1,
            "strict_succeeded_count": 1,
            "strict_skipped_count": 0,
            "events": [
                {
                    "geo_profile_id": "la",
                    "requested": True,
                    "attempted": True,
                    "succeeded": True,
                    "cache_hit": False,
                    "triggers": ["manual_force", "managed_probe_failed"],
                    "skipped_reason": None,
                    "error": None,
                }
            ],
        },
    )

    skipped_run = repository.create_run(
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    repository.complete_run(
        skipped_run,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "strict_requested_count": 1,
            "strict_attempted_count": 0,
            "strict_succeeded_count": 0,
            "strict_skipped_count": 1,
            "events": [
                {
                    "geo_profile_id": "tx",
                    "requested": True,
                    "attempted": False,
                    "succeeded": False,
                    "cache_hit": False,
                    "triggers": ["low_confidence:0.50"],
                    "skipped_reason": "insufficient_credits",
                    "error": None,
                }
            ],
        },
    )

    analytics = repository.verification_analytics(
        owner_id="tenant-1",
        since=datetime.now(UTC) - timedelta(hours=1),
        until=datetime.now(UTC) + timedelta(hours=1),
    )

    assert analytics["run_count"] == 3
    assert analytics["strict_requested"] == 3
    assert analytics["strict_attempted"] == 1
    assert analytics["strict_succeeded"] == 2
    assert analytics["strict_skipped"] == 1
    assert analytics["manual_requested"] == 1
    assert analytics["automatic_requested"] == 2
    assert analytics["unclassified_requested"] == 0
    assert analytics["cache_hits"] == 1
    assert analytics["recovered_failed_geos"] == 1
    assert analytics["trigger_counts"] == {
        "low_confidence": 1,
        "managed_probe_failed": 1,
        "manual_force": 1,
        "rank_movement": 1,
    }
    assert analytics["skip_reason_counts"] == {
        "insufficient_credits": 1,
    }
    assert len(analytics["daily"]) == 1
    assert analytics["daily"][0]["requested"] == 3
    assert analytics["daily"][0]["cache_hits"] == 1


def test_previous_observations_uses_valid_geo_before_current_start() -> None:
    repository = repo()
    older = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    repository.save_observations(older, [observation()])
    repository.complete_run(older, status="succeeded", settled_probe_count=1)
    current = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    newer = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    repository.save_observations(newer, [observation()])
    repository.complete_run(newer, status="succeeded", settled_probe_count=1)
    selected = repository.previous_observations(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", geo_profile_id="us-ny-10001",
        exclude_run_id=current,
    )
    assert len(selected) == 1
    assert selected[0].asin == "B0TARGET01"


def test_previous_observations_skips_newest_run_without_matching_geo() -> None:
    repository = repo()
    older = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    repository.save_observations(older, [observation()])
    repository.complete_run(older, status="succeeded", settled_probe_count=1)
    empty = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    repository.complete_run(empty, status="succeeded", settled_probe_count=0)
    current = repository.create_run(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", requested_probe_count=1,
    )
    selected = repository.previous_observations(
        owner_id="tenant-1", marketplace="amazon.com",
        keyword="walking pad", geo_profile_id="us-ny-10001",
        exclude_run_id=current,
    )
    assert [item.asin for item in selected] == ["B0TARGET01"]
