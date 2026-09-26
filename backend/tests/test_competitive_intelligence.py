from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.competitive import CompetitiveIntelligenceService
from amazon_geo_rank_monitor.domain.models import SerpProduct, SerpResult
from amazon_geo_rank_monitor.repositories.competitive_repository import (
    CompetitiveRepository,
)
from amazon_geo_rank_monitor.repositories.models import (
    Base,
    RankJobRow,
    RankRunRow,
)


class FakeMonitorRepository:
    def get(self, monitor_id: str, *, owner_id: str):
        if monitor_id != "monitor-1" or owner_id != "tenant-a":
            return None
        return {
            "id": "monitor-1",
            "name": "Walking Pad",
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["OWNED1"],
            "geo_profile_ids": ["ny", "la"],
        }


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = CompetitiveRepository(engine)
    service = CompetitiveIntelligenceService(
        repository=repository,
        monitor_repository=FakeMonitorRepository(),
    )
    return engine, repository, service


def add_run(
    engine,
    *,
    run_id: str,
    owner_id: str = "tenant-a",
    monitor_id: str = "monitor-1",
    completed_at: datetime,
):
    with Session(engine) as session:
        session.add(
            RankRunRow(
                id=run_id,
                owner_id=owner_id,
                marketplace="amazon.com",
                keyword="walking pad",
                status="succeeded",
                requested_probe_count=2,
                settled_probe_count=2,
                completed_at=completed_at,
            )
        )
        session.add(
            RankJobRow(
                id=f"job-{run_id}",
                owner_id=owner_id,
                monitor_target_id=monitor_id,
                provider_mode="managed",
                request_payload={},
                status="succeeded",
                run_id=run_id,
                completed_at=completed_at,
            )
        )
        session.commit()


def test_capture_merges_channels_and_preserves_cache_provenance() -> None:
    engine, repository, service = build_service()
    now = datetime.now(UTC)
    add_run(engine, run_id="run-1", completed_at=now)

    result = SerpResult(
        organic_products=[
            SerpProduct(asin="COMP1", position=2, title="Competitor One"),
            SerpProduct(asin="OWNED1", position=5, title="Owned"),
        ],
        sponsored_products=[
            SerpProduct(asin="COMP1", position=1, sponsored=True),
        ],
        absolute_products=[
            SerpProduct(asin="COMP1", position=3),
        ],
    )
    service.capture_probe(
        owner_id="tenant-a",
        run_id="run-1",
        geo_profile_id="ny",
        result=result,
        search_depth=20,
        probe_source="cache",
        cache_age_seconds=42,
        observed_at=now - timedelta(seconds=42),
    )

    rows = repository.monitor_points(
        owner_id="tenant-a",
        monitor_target_id="monitor-1",
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=1),
    )
    comp = next(row for row in rows if row["asin"] == "COMP1")
    assert len([row for row in rows if row["asin"] == "COMP1"]) == 1
    assert comp["organic_position"] == 2
    assert comp["sponsored_position"] == 1
    assert comp["absolute_position"] == 3
    assert comp["probe_source"] == "cache"
    assert comp["cache_age_seconds"] == 42
    assert comp["title"] == "Competitor One"


def test_summary_calculates_share_coverage_and_excludes_tracked_asin() -> None:
    engine, repository, service = build_service()
    now = datetime.now(UTC)
    add_run(engine, run_id="run-1", completed_at=now - timedelta(minutes=10))
    add_run(engine, run_id="run-2", completed_at=now)

    repository.save_probe(
        owner_id="tenant-a",
        run_id="run-1",
        geo_profile_id="ny",
        rows=[
            {"asin": "COMP1", "title": "One", "organic_position": 2},
            {"asin": "COMP2", "title": "Two", "organic_position": 5},
            {"asin": "OWNED1", "title": "Owned", "organic_position": 1},
        ],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now - timedelta(minutes=10),
    )
    repository.save_probe(
        owner_id="tenant-a",
        run_id="run-1",
        geo_profile_id="la",
        rows=[
            {"asin": "COMP1", "title": "One", "organic_position": 4},
            {"asin": "COMP2", "title": "Two", "sponsored_position": 1},
        ],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now - timedelta(minutes=10),
    )
    repository.save_probe(
        owner_id="tenant-a",
        run_id="run-2",
        geo_profile_id="ny",
        rows=[
            {"asin": "COMP1", "title": "One New", "organic_position": 1},
            {"asin": "COMP2", "title": "Two", "organic_position": 8},
        ],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now,
    )
    repository.save_probe(
        owner_id="tenant-a",
        run_id="run-2",
        geo_profile_id="la",
        rows=[
            {"asin": "COMP1", "title": "One New", "organic_position": 3},
        ],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now,
    )

    summary = service.summary(
        owner_id="tenant-a",
        monitor_target_id="monitor-1",
        hours=24,
        top_n=10,
    )

    assert summary["probe_count"] == 4
    asins = [row["asin"] for row in summary["competitors"]]
    assert "OWNED1" not in asins
    assert asins[0] == "COMP1"
    comp1 = summary["competitors"][0]
    assert comp1["organic_appearances"] == 4
    assert comp1["organic_probe_coverage_pct"] == 100.0
    assert comp1["best_organic_rank"] == 1
    assert comp1["latest_organic_rank"] == 2.0
    assert comp1["organic_rank_change"] == -1.0
    assert comp1["title"] == "One New"
    assert comp1["organic_sov_pct"] > 60


def test_monitor_query_is_tenant_scoped() -> None:
    engine, repository, service = build_service()
    now = datetime.now(UTC)
    add_run(engine, run_id="run-a", completed_at=now)
    add_run(
        engine,
        run_id="run-b",
        owner_id="tenant-b",
        monitor_id="monitor-1",
        completed_at=now,
    )
    repository.save_probe(
        owner_id="tenant-a",
        run_id="run-a",
        geo_profile_id="ny",
        rows=[{"asin": "SAFE", "organic_position": 2}],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now,
    )
    repository.save_probe(
        owner_id="tenant-b",
        run_id="run-b",
        geo_profile_id="ny",
        rows=[{"asin": "LEAK", "organic_position": 1}],
        probe_source="upstream",
        cache_age_seconds=None,
        observed_at=now,
    )

    summary = service.summary(
        owner_id="tenant-a",
        monitor_target_id="monitor-1",
        hours=1,
        top_n=10,
    )
    assert [row["asin"] for row in summary["competitors"]] == ["SAFE"]


def test_trend_returns_run_level_rank_and_geo_coverage() -> None:
    engine, repository, service = build_service()
    now = datetime.now(UTC)
    add_run(engine, run_id="run-1", completed_at=now)
    for geo, rank in (("ny", 2), ("la", 6)):
        repository.save_probe(
            owner_id="tenant-a",
            run_id="run-1",
            geo_profile_id=geo,
            rows=[{"asin": "COMP1", "organic_position": rank}],
            probe_source="upstream",
            cache_age_seconds=None,
            observed_at=now,
        )

    trend = service.trend(
        owner_id="tenant-a",
        monitor_target_id="monitor-1",
        hours=1,
        top_n=5,
        asins=["COMP1"],
    )
    assert len(trend["series"]) == 1
    point = trend["series"][0]
    assert point["average_organic_rank"] == 2.0
    assert point["organic_probe_coverage_pct"] == 50.0
