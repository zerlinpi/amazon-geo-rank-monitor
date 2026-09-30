"""Playwright-only fixture app. Never imported by production entry points."""
import asyncio
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from offline_stack import build_offline_services, offline_worker

from amazon_geo_rank_monitor.api.app import create_app
from amazon_geo_rank_monitor.domain.models import RankSnapshot
from amazon_geo_rank_monitor.repositories.models import RankRunRow

directory = tempfile.TemporaryDirectory(prefix="agrm-e2e-")
services, provider = build_offline_services(
    f"sqlite+pysqlite:///{Path(directory.name) / 'e2e.db'}",
)
for zone in ["utc", "new_york", "singapore"]:
    account = services.accounts.register(
        email=f"{zone}@example.com", password="offline-secure-password",
        display_name="Browser owner", workspace_name=f"E2E {zone}",
    )
    owner = account.principal.owner_id
    services.billing_repository.grant(owner_id=owner, credits=500, idempotency_key=f"seed:{zone}")
    for index in range(105):
        run_id = str(uuid4())
        started_at = datetime.now(UTC) - timedelta(hours=index * 2, minutes=1)
        with services.rank_repository._sessions.begin() as session:
            session.add(RankRunRow(
                id=run_id, owner_id=owner, marketplace="amazon.com", keyword="trailer hitch",
                status="failed" if index == 0 else "succeeded", requested_probe_count=1,
                started_at=started_at, completed_at=started_at + timedelta(seconds=2),
                verification_metadata={},
            ))
        services.rank_repository.save_snapshots(run_id, [RankSnapshot(
            asin="B0TARGET01", weighted_rank=5, found_weight=100, missing_weight=0, confidence=1,
        )])


async def work():
    worker = offline_worker(services)
    while True:
        await worker.run_once()
        await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(work())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        services.database_engine.dispose()
        directory.cleanup()


app = create_app(
    services, cors_origins=["http://127.0.0.1:4173"],
    api_rate_limit_per_minute=10000, auth_rate_limit_per_minute=1000,
)
app.router.lifespan_context = lifespan
