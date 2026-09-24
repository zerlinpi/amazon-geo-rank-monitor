from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.scheduling.service import MonitorScheduler


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return AppServices(
        tenant_repository=None,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=None,
        api_keys=None,
        provider_registry=None,
    )


def create_scheduled_monitor(services):
    owner_id = "tenant-a"
    geo = services.geo_repository.create(
        owner_id=owner_id,
        profile=GeoProfile(
            id="ny",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=Decimal("100"),
        ),
    )
    return services.monitor_repository.create(
        owner_id=owner_id,
        name="Walking Pad",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[geo["id"]],
        search_depth=100,
        provider_mode="managed",
        schedule="*/15 * * * *",
    )


def test_scheduler_dispatch_is_idempotent_per_cron_slot() -> None:
    services = build_services()
    monitor = create_scheduled_monitor(services)
    now = monitor["created_at"].astimezone(UTC) + timedelta(minutes=16)
    scheduler = MonitorScheduler(services=services)

    first = scheduler.run_once(now=now)
    second = scheduler.run_once(now=now)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["job_id"] == second[0]["job_id"]
    jobs = services.job_repository.list_for_monitor(
        owner_id=monitor["owner_id"],
        monitor_target_id=monitor["id"],
    )
    assert len(jobs) == 1


def test_invalid_monitor_schedule_is_rejected() -> None:
    services = build_services()
    owner_id = "tenant-a"
    geo = services.geo_repository.create(
        owner_id=owner_id,
        profile=GeoProfile(
            id="ny",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=Decimal("100"),
        ),
    )

    with pytest.raises(ValueError, match="5-field cron"):
        services.monitor_repository.create(
            owner_id=owner_id,
            name="Bad schedule",
            marketplace="amazon.com",
            keyword="walking pad",
            asins=["B0TARGET01"],
            geo_profile_ids=[geo["id"]],
            search_depth=100,
            provider_mode="managed",
            schedule="every hour",
        )
