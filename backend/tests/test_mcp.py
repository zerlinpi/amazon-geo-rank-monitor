from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import GeoProfile, SerpProduct, SerpResult
from amazon_geo_rank_monitor.mcp.server import (
    build_local_mcp_server,
    build_streamable_http_app,
)
from amazon_geo_rank_monitor.mcp.tools import RankMcpTools
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=4, page=1),
            ]
        )


def services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    return (
        AppServices(
            tenant_repository=tenants,
            geo_repository=GeoRepository(engine),
            monitor_repository=MonitorRepository(engine),
            job_repository=JobRepository(engine),
            rank_repository=RankRepository(engine),
            api_keys=ApiKeyService(repository=tenants, pepper="pepper"),
            provider_registry=ProviderRegistry(
                managed=FakeProvider(),
                strict=FakeProvider(),
            ),
        ),
        tenants,
    )


@pytest.mark.asyncio
async def test_mcp_check_rank_uses_shared_rank_service() -> None:
    app_services, tenants = services()
    tenant = tenants.create_tenant("A")
    geo = app_services.geo_repository.create(
        owner_id=tenant["id"],
        profile=GeoProfile(
            id="ny",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            ip_postal_code="10001",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=Decimal("100"),
        ),
    )
    tools = RankMcpTools(services=app_services, owner_id=tenant["id"])

    result = await tools.check_rank(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[geo["id"]],
        search_depth=100,
        provider_mode="managed",
    )

    assert result["status"] == "succeeded"
    saved = app_services.rank_repository.get_run(
        result["run_id"],
        owner_id=tenant["id"],
    )
    assert saved["snapshots"][0]["weighted_rank"] == Decimal("1.00")


@pytest.mark.asyncio
async def test_local_mcp_server_registers_expected_tools() -> None:
    app_services, tenants = services()
    tenant = tenants.create_tenant("A")
    server = build_local_mcp_server(
        RankMcpTools(services=app_services, owner_id=tenant["id"])
    )
    tool_names = {tool.name for tool in await server.list_tools()}
    assert {
        "check_rank",
        "list_geo_profiles",
        "create_monitor",
        "run_monitor",
        "get_rank_run",
        "get_rank_history",
    } <= tool_names


def test_streamable_http_refuses_to_start_without_oauth_configuration() -> None:
    app_services, _ = services()
    with pytest.raises(ValueError):
        build_streamable_http_app(
            services=app_services,
            auth=None,
            token_verifier=None,
            tenant_resolver=None,
        )


def test_mcp_run_monitor_snapshots_manual_force_intent() -> None:
    app_services, tenants = services()
    tenant = tenants.create_tenant("A")
    geo = app_services.geo_repository.create(
        owner_id=tenant["id"],
        profile=GeoProfile(
            id="ny",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            ip_postal_code="10001",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=Decimal("100"),
        ),
    )
    monitor = app_services.monitor_repository.create(
        owner_id=tenant["id"],
        name="Walking Pad",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[geo["id"]],
        search_depth=100,
        provider_mode="managed",
    )
    tools = RankMcpTools(services=app_services, owner_id=tenant["id"])

    job = tools.run_monitor(
        monitor_id=monitor["id"],
        force_strict_verification=True,
    )

    assert (
        job["request_payload"]["_verification_policy"][
            "force_strict_verification"
        ]
        is True
    )
