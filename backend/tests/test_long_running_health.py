import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, update
from test_worker_status import PartialProvider, build_request

from amazon_geo_rank_monitor import main
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.operations import health
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base, WorkerHeartbeatRow
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.worker_status_repository import WorkerStatusRepository
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


def database(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'heartbeats.db'}")
    Base.metadata.create_all(engine)
    return engine, WorkerStatusRepository(engine)


async def test_running_job_refreshes_health_before_lease_renewal(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False)
    engine, workers = database(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    class SlowProvider(PartialProvider):
        async def search(self, **kwargs):
            started.set()
            await release.wait()
            return await super().search(**kwargs)

    jobs = JobRepository(engine)
    job = jobs.enqueue(
        owner_id="owner", provider_mode="managed",
        request_payload=build_request().model_dump(mode="json"),
    )
    worker = RankWorker(
        job_repository=jobs, rank_repository=RankRepository(engine),
        provider_registry=ProviderRegistry(managed=SlowProvider(), strict=SlowProvider()),
        worker_status_repository=workers, worker_id="slow-worker", lease_seconds=900,
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        stale = datetime.now(UTC) - timedelta(minutes=5)
        with engine.begin() as connection:
            connection.execute(update(WorkerHeartbeatRow).values(last_seen_at=stale))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            row = workers.list()[0]
            if row["last_seen_at"].replace(tzinfo=UTC) > stale:
                break
            await asyncio.sleep(0.01)
        assert row["last_seen_at"].replace(tzinfo=UTC) > stale
        assert row["last_job_id"] == job["id"]
        assert row["status"] == "running"
        assert row["processed_jobs"] == 0
    finally:
        release.set()
        await task
        engine.dispose()


async def test_scheduler_refreshes_health_during_blocking_report(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False)
    engine, workers = database(tmp_path)
    observed = []

    def slow_report():
        initial = workers.list()[0]["last_seen_at"]
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            row = workers.list()[0]
            if row["last_seen_at"] > initial:
                observed.append(row)
                break
            time.sleep(0.01)
        return []

    monkeypatch.setattr(main, "AppSettings", lambda: SimpleNamespace(scheduler_id="scheduler"))
    monkeypatch.setattr(main, "build_services", lambda settings: SimpleNamespace(
        worker_status_repository=workers,
    ))
    monkeypatch.setattr(main, "MonitorScheduler", lambda **kw: SimpleNamespace(run_once=lambda: []))
    monkeypatch.setattr(main, "ReportScheduler", lambda **kw: SimpleNamespace(run_once=slow_report))
    try:
        await main._scheduler_loop(once=True)
        assert observed, "A blocking report must not make the scheduler heartbeat stale"
        assert observed[0]["status"] == "running"
        assert workers.list()[0]["status"] == "idle"
    finally:
        engine.dispose()
