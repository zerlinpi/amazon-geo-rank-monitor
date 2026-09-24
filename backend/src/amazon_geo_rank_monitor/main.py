from __future__ import annotations

import argparse
import asyncio
import json
import socket

import uvicorn

from amazon_geo_rank_monitor.api.app import create_app
from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.mcp.server import build_local_mcp_server
from amazon_geo_rank_monitor.mcp.tools import RankMcpTools
from amazon_geo_rank_monitor.runtime import build_services
from amazon_geo_rank_monitor.scheduling.service import MonitorScheduler
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


def api_main() -> None:
    settings = AppSettings()
    app = create_app(
        build_services(settings),
        cors_origins=settings.cors_origin_list,
        api_rate_limit_per_minute=settings.api_rate_limit_per_minute,
    )
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
    )


def bootstrap_main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a tenant and API key")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    settings = AppSettings()
    services = build_services(settings)
    tenant = services.tenant_repository.create_tenant(args.name)
    key = services.api_keys.create(owner_id=tenant["id"], name="bootstrap")
    print(
        json.dumps(
            {
                "tenant_id": tenant["id"],
                "api_key": key.plaintext,
            }
        )
    )


async def _worker_loop(*, once: bool) -> None:
    settings = AppSettings()
    services = build_services(settings)
    worker = RankWorker(
        job_repository=services.job_repository,
        rank_repository=services.rank_repository,
        provider_registry=services.provider_registry,
        billing_repository=services.billing_repository,
        rate_card=services.rate_card,
        worker_status_repository=services.worker_status_repository,
        worker_id=settings.worker_id or socket.gethostname(),
        lease_seconds=settings.job_lease_seconds,
        retry_base_seconds=settings.job_retry_base_seconds,
        retry_max_seconds=settings.job_retry_max_seconds,
    )

    while True:
        job = await worker.run_once()
        if once:
            return
        if job is None:
            await asyncio.sleep(settings.worker_poll_seconds)


def worker_main() -> None:
    parser = argparse.ArgumentParser(description="Run rank jobs")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(_worker_loop(once=args.once))


async def _scheduler_loop(*, once: bool) -> None:
    settings = AppSettings()
    services = build_services(settings)
    scheduler = MonitorScheduler(services=services)
    scheduler_id = settings.scheduler_id or f"scheduler-{socket.gethostname()}"

    while True:
        services.worker_status_repository.heartbeat(
            worker_id=scheduler_id,
            worker_type="scheduler",
            status="running",
        )
        outcomes = scheduler.run_once()
        successful = [item for item in outcomes if item.get("job_id")]
        errors = [item for item in outcomes if item.get("error")]
        services.worker_status_repository.heartbeat(
            worker_id=scheduler_id,
            worker_type="scheduler",
            status="error" if errors else "idle",
            last_job_id=successful[-1]["job_id"] if successful else None,
            last_error=errors[0]["error"] if errors else None,
            processed_delta=len(successful),
        )
        if outcomes:
            print(json.dumps(outcomes, default=str))
        if once:
            return
        await asyncio.sleep(settings.scheduler_poll_seconds)


def scheduler_main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch due monitor schedules")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(_scheduler_loop(once=args.once))


def mcp_main() -> None:
    settings = AppSettings()
    if not settings.mcp_tenant_id:
        raise ConfigurationError("MCP_TENANT_ID is required for local stdio MCP")
    services = build_services(settings)
    server = build_local_mcp_server(
        RankMcpTools(
            services=services,
            owner_id=settings.mcp_tenant_id,
        )
    )
    server.run("stdio")
