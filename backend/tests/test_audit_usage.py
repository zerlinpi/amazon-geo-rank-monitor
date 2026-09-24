from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import SerpResult
from amazon_geo_rank_monitor.repositories.audit_repository import AuditRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository
from amazon_geo_rank_monitor.repositories.worker_status_repository import (
    WorkerStatusRepository,
)


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult()


def build_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    audit = AuditRepository(engine)
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=RankRepository(engine),
        api_keys=keys,
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
        database_engine=engine,
        worker_status_repository=WorkerStatusRepository(engine),
        audit_repository=audit,
    )
    return TestClient(create_app(services)), tenants, keys, audit


def test_authenticated_requests_update_key_usage_and_write_audit_event() -> None:
    client, tenants, keys, audit = build_client()
    tenant = tenants.create_tenant("Acme")
    key = keys.create(owner_id=tenant["id"], name="root")

    response = client.get(
        "/api/v1/geo-profiles",
        headers={
            "X-API-Key": key.plaintext,
            "X-Request-ID": "audit-request-1",
            "User-Agent": "agrm-test-client/1.0",
        },
    )

    assert response.status_code == 200
    stored = tenants.get_api_key(key.id, owner_id=tenant["id"])
    assert stored["usage_count"] == 1
    assert stored["last_used_at"] is not None
    assert stored["last_used_ip"] == "testclient"

    events = audit.list(owner_id=tenant["id"])
    assert len(events) == 1
    event = events[0]
    assert event["api_key_id"] == key.id
    assert event["request_id"] == "audit-request-1"
    assert event["method"] == "GET"
    assert event["path"] == "/api/v1/geo-profiles"
    assert event["status_code"] == 200
    assert event["client_ip"] == "testclient"
    assert event["user_agent"] == "agrm-test-client/1.0"


def test_audit_endpoint_is_tenant_scoped() -> None:
    client, tenants, keys, audit = build_client()
    tenant_a = tenants.create_tenant("A")
    tenant_b = tenants.create_tenant("B")
    key_a = keys.create(owner_id=tenant_a["id"], name="A root")
    key_b = keys.create(owner_id=tenant_b["id"], name="B root")

    audit.record(
        owner_id=tenant_b["id"],
        api_key_id=key_b.id,
        request_id="tenant-b-event",
        method="POST",
        path="/api/v1/monitors",
        status_code=201,
        client_ip="10.0.0.2",
        user_agent="test",
    )

    response = client.get(
        "/api/v1/system/audit",
        headers={"X-API-Key": key_a.plaintext},
    )

    assert response.status_code == 200
    events = response.json()
    assert events
    assert all(event["owner_id"] == tenant_a["id"] for event in events)
    assert all(event["request_id"] != "tenant-b-event" for event in events)
