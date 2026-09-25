from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.analytics import AnalyticsService
from amazon_geo_rank_monitor.notifications.email import MemoryEmailSender
from amazon_geo_rank_monitor.reports import ReportService
from amazon_geo_rank_monitor.repositories.analytics_repository import (
    AnalyticsRepository,
)
from amazon_geo_rank_monitor.repositories.models import (
    Base,
    GeoProfileRow,
    MonitorTargetAsinRow,
    MonitorTargetGeoRow,
    MonitorTargetRow,
    RankJobRow,
    RankObservationRow,
    RankRunRow,
    RankSnapshotRow,
    TenantRow,
)
from amazon_geo_rank_monitor.repositories.monitor_repository import (
    MonitorRepository,
)
from amazon_geo_rank_monitor.repositories.report_repository import ReportRepository
from amazon_geo_rank_monitor.scheduling.reports import ReportScheduler

OWNER_ID = "owner-1"
OTHER_OWNER_ID = "owner-2"
MONITOR_ID = "monitor-1"
OTHER_MONITOR_ID = "monitor-2"
ASIN = "B000TEST01"
GEO_ID = "geo-1"


def build_stack():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with sessions.begin() as session:
        session.add_all(
            [
                TenantRow(id=OWNER_ID, name="Acme"),
                TenantRow(id=OTHER_OWNER_ID, name="Other"),
                GeoProfileRow(
                    id=GEO_ID,
                    owner_id=OWNER_ID,
                    name="New York",
                    marketplace="amazon.com",
                    ip_country="US",
                    ip_state="NY",
                    ip_city="New York",
                    ip_postal_code="10001",
                    delivery_country="US",
                    delivery_postal_code="10001",
                    device="desktop",
                    weight=Decimal("1"),
                    enabled=True,
                ),
                MonitorTargetRow(
                    id=MONITOR_ID,
                    owner_id=OWNER_ID,
                    name="Core keyword",
                    marketplace="amazon.com",
                    keyword="walking pad",
                    search_depth=100,
                    provider_mode="managed",
                    schedule=None,
                    enabled=True,
                ),
                MonitorTargetAsinRow(
                    monitor_target_id=MONITOR_ID,
                    asin=ASIN,
                ),
                MonitorTargetGeoRow(
                    monitor_target_id=MONITOR_ID,
                    geo_profile_id=GEO_ID,
                ),
                MonitorTargetRow(
                    id=OTHER_MONITOR_ID,
                    owner_id=OTHER_OWNER_ID,
                    name="Other monitor",
                    marketplace="amazon.com",
                    keyword="walking pad",
                    search_depth=100,
                    provider_mode="managed",
                    schedule=None,
                    enabled=True,
                ),
            ]
        )

        for index, rank in enumerate((20, 8), start=1):
            completed_at = now - timedelta(hours=48 - index * 24)
            run_id = f"run-{index}"
            session.add(
                RankRunRow(
                    id=run_id,
                    owner_id=OWNER_ID,
                    marketplace="amazon.com",
                    keyword="walking pad",
                    status="succeeded",
                    requested_probe_count=1,
                    settled_probe_count=1,
                    started_at=completed_at - timedelta(minutes=1),
                    completed_at=completed_at,
                )
            )
            session.add(
                RankJobRow(
                    id=f"job-{index}",
                    owner_id=OWNER_ID,
                    monitor_target_id=MONITOR_ID,
                    provider_mode="managed",
                    request_payload={},
                    status="succeeded",
                    available_at=completed_at - timedelta(minutes=2),
                    completed_at=completed_at,
                    run_id=run_id,
                )
            )
            session.add(
                RankSnapshotRow(
                    rank_run_id=run_id,
                    asin=ASIN,
                    weighted_rank=Decimal(rank),
                    found_weight=Decimal("1"),
                    missing_weight=Decimal("0"),
                    confidence=Decimal("0.95"),
                    created_at=completed_at,
                )
            )
            session.add(
                RankObservationRow(
                    rank_run_id=run_id,
                    asin=ASIN,
                    geo_profile_id=GEO_ID,
                    provider="fake",
                    verification_level="managed",
                    status="ok",
                    found=True,
                    organic_rank=rank,
                    absolute_rank=rank,
                    sponsored_rank=None,
                    effective_rank=rank,
                    page=1,
                    observed_at=completed_at,
                )
            )

        unrelated_at = now - timedelta(hours=2)
        session.add(
            RankRunRow(
                id="run-unrelated",
                owner_id=OTHER_OWNER_ID,
                marketplace="amazon.com",
                keyword="walking pad",
                status="succeeded",
                requested_probe_count=1,
                settled_probe_count=1,
                started_at=unrelated_at,
                completed_at=unrelated_at,
            )
        )
        session.add(
            RankJobRow(
                id="job-unrelated",
                owner_id=OTHER_OWNER_ID,
                monitor_target_id=OTHER_MONITOR_ID,
                provider_mode="managed",
                request_payload={},
                status="succeeded",
                available_at=unrelated_at,
                completed_at=unrelated_at,
                run_id="run-unrelated",
            )
        )
        session.add(
            RankSnapshotRow(
                rank_run_id="run-unrelated",
                asin=ASIN,
                weighted_rank=Decimal("1"),
                found_weight=Decimal("1"),
                missing_weight=Decimal("0"),
                confidence=Decimal("1"),
                created_at=unrelated_at,
            )
        )

    monitor_repository = MonitorRepository(engine)
    analytics = AnalyticsService(
        repository=AnalyticsRepository(engine),
        monitor_repository=monitor_repository,
    )
    report_repository = ReportRepository(engine)
    mailer = MemoryEmailSender()
    reports = ReportService(
        repository=report_repository,
        analytics=analytics,
        monitor_repository=monitor_repository,
        email_sender=mailer,
        encryption_key="test-report-encryption-key",
    )
    return engine, analytics, report_repository, reports, mailer


def test_analytics_summary_and_csv_are_monitor_scoped() -> None:
    _, analytics, _, _, _ = build_stack()

    trend = analytics.trend(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        hours=168,
    )
    assert [item["run_id"] for item in trend["aggregate"]] == [
        "run-1",
        "run-2",
    ]
    assert all(item["weighted_rank"] != Decimal("1") for item in trend["aggregate"])

    summary = analytics.summary(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        hours=168,
    )
    assert summary["run_count"] == 2
    asin = summary["asins"][0]
    assert asin["first_rank"] == Decimal("20")
    assert asin["latest_rank"] == Decimal("8")
    assert asin["change"] == Decimal("-12")
    assert asin["best_rank"] == Decimal("8")
    assert asin["worst_rank"] == Decimal("20")
    assert asin["average_found_rate"] == Decimal("1")

    csv_text, filename = analytics.export_csv(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        hours=168,
    )
    assert "run-1" in csv_text
    assert "run-2" in csv_text
    assert "run-unrelated" not in csv_text
    assert filename.endswith("-aggregate-" + datetime.now(UTC).date().isoformat() + ".csv")


def test_report_recipients_are_encrypted_and_delivery_is_idempotent() -> None:
    _, _, repository, reports, mailer = build_stack()
    schedule = reports.create_schedule(
        owner_id=OWNER_ID,
        name="Weekly rank review",
        monitor_target_ids=[MONITOR_ID],
        recipients=["Ops@Example.com"],
        schedule="0 9 * * 1",
        lookback_hours=168,
        include_csv=True,
    )
    assert schedule["recipients"] == ["ops@example.com"]

    raw = repository.get_schedule(
        owner_id=OWNER_ID,
        schedule_id=schedule["id"],
    )
    assert "ops@example.com" not in raw["recipients_encrypted"]

    scheduled_for = datetime.now(UTC).replace(second=0, microsecond=0)
    first = reports.dispatch_schedule(
        owner_id=OWNER_ID,
        schedule_id=schedule["id"],
        scheduled_for=scheduled_for,
    )
    assert first is not None
    assert first["status"] == "sent"
    assert first["sent_count"] == 1
    assert len(mailer.messages) == 1
    assert mailer.messages[0].attachments
    assert mailer.messages[0].attachments[0].filename.endswith(".csv")

    duplicate = reports.dispatch_schedule(
        owner_id=OWNER_ID,
        schedule_id=schedule["id"],
        scheduled_for=scheduled_for,
    )
    assert duplicate is None
    assert len(mailer.messages) == 1


def test_report_scheduler_dispatches_latest_slot_once() -> None:
    _, _, repository, reports, mailer = build_stack()
    schedule = reports.create_schedule(
        owner_id=OWNER_ID,
        name="Every minute",
        monitor_target_ids=[MONITOR_ID],
        recipients=["ops@example.com"],
        schedule="* * * * *",
        lookback_hours=168,
        include_csv=False,
    )
    raw = repository.get_schedule(
        owner_id=OWNER_ID,
        schedule_id=schedule["id"],
    )
    now = raw["created_at"] + timedelta(minutes=2)

    services = type(
        "Services",
        (),
        {
            "report_repository": repository,
            "reports": reports,
        },
    )()
    scheduler = ReportScheduler(services=services)
    first = scheduler.run_once(now=now)
    second = scheduler.run_once(now=now)

    assert len(first) == 1
    assert first[0]["delivery_status"] == "sent"
    assert second == []
    assert len(mailer.messages) == 1


def test_report_schedule_rejects_foreign_monitor() -> None:
    _, _, _, reports, _ = build_stack()
    try:
        reports.create_schedule(
            owner_id=OWNER_ID,
            name="Invalid",
            monitor_target_ids=[OTHER_MONITOR_ID],
            recipients=["ops@example.com"],
            schedule="0 9 * * 1",
            lookback_hours=168,
            include_csv=True,
        )
    except KeyError:
        pass
    else:
        raise AssertionError("foreign monitor schedule should be rejected")
