"""Regression tests for bounded SQL reads in legacy full-detail run history."""

from decimal import Decimal

from sqlalchemy import create_engine, event

from amazon_geo_rank_monitor.domain.models import (
    ProbeStatus,
    RankObservation,
    RankSnapshot,
    VerificationLevel,
)
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


def test_full_history_batches_details_without_cross_tenant_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = RankRepository(engine)

    own_runs = []
    for index in range(3):
        run_id = repository.create_run(
            owner_id="workspace-a",
            marketplace="amazon.com",
            keyword="walking pad",
            requested_probe_count=1,
        )
        repository.save_observations(
            run_id,
            [
                RankObservation(
                    asin=f"B0TEST{index:04d}",
                    geo_profile_id="us-ny-10001",
                    provider="oxylabs",
                    verification_level=VerificationLevel.MANAGED,
                    status=ProbeStatus.SUCCESS_FOUND,
                    found=True,
                    effective_rank=index + 1,
                    organic_rank=index + 1,
                )
            ],
        )
        repository.save_snapshots(
            run_id,
            [
                RankSnapshot(
                    asin=f"B0TEST{index:04d}",
                    weighted_rank=Decimal(index + 1),
                    found_weight=Decimal(1),
                    missing_weight=Decimal(0),
                )
            ],
        )
        repository.complete_run(run_id, status="succeeded", settled_probe_count=1)
        own_runs.append(run_id)

    foreign = repository.create_run(
        owner_id="workspace-b",
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=0,
    )
    repository.complete_run(foreign, status="succeeded", settled_probe_count=0)

    expected = {run_id: repository.get_run(run_id, owner_id="workspace-a") for run_id in own_runs}
    query_count = 0

    def count_queries(*_args: object) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        actual = repository.list_runs(owner_id="workspace-a", limit=3)
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)

    assert query_count == 3
    assert {run["id"] for run in actual} == set(own_runs)
    assert {run["id"]: run for run in actual} == expected
    assert all(len(run["observations"]) == 1 for run in actual)
    assert all(len(run["snapshots"]) == 1 for run in actual)
    assert repository.list_runs(owner_id="workspace-a", limit=1)[0]["id"] in own_runs


def test_empty_full_history_avoids_detail_queries() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = RankRepository(engine)
    query_count = 0

    def count_queries(*_args: object) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        assert repository.list_runs(owner_id="no-runs") == []
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)

    assert query_count == 1
