from decimal import Decimal

from sqlalchemy import create_engine

from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


def repositories():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return (
        TenantRepository(engine),
        GeoRepository(engine),
        MonitorRepository(engine),
    )


def sample_geo(profile_id: str = "us-ny-10001") -> GeoProfile:
    return GeoProfile(
        id=profile_id,
        name="New York",
        marketplace="amazon.com",
        ip_country="US",
        ip_state="NY",
        ip_city="New York",
        ip_postal_code="10001",
        delivery_country="US",
        delivery_postal_code="10001",
        device="desktop",
        weight=Decimal("30"),
    )


def test_api_key_is_hashed_and_revocation_blocks_authentication() -> None:
    tenant_repo, _, _ = repositories()
    tenant = tenant_repo.create_tenant("Acme")
    service = ApiKeyService(repository=tenant_repo, pepper="test-pepper")

    created = service.create(owner_id=tenant["id"], name="default")
    assert created.plaintext.startswith("agrm_")
    stored = tenant_repo.get_api_key(created.id, owner_id=tenant["id"])
    assert stored["key_hash"] != created.plaintext
    assert created.plaintext not in repr(stored)

    authenticated = service.authenticate(created.plaintext)
    assert authenticated == tenant["id"]

    service.revoke(created.id, owner_id=tenant["id"])
    assert service.authenticate(created.plaintext) is None


def test_geo_profiles_are_owner_scoped() -> None:
    tenant_repo, geo_repo, _ = repositories()
    a = tenant_repo.create_tenant("A")
    b = tenant_repo.create_tenant("B")
    profile = geo_repo.create(owner_id=a["id"], profile=sample_geo())

    assert geo_repo.get(profile["id"], owner_id=a["id"])["name"] == "New York"
    assert geo_repo.get(profile["id"], owner_id=b["id"]) is None
    assert geo_repo.list(owner_id=b["id"]) == []


def test_monitor_is_owner_scoped_and_keeps_asins_and_geos() -> None:
    tenant_repo, geo_repo, monitor_repo = repositories()
    a = tenant_repo.create_tenant("A")
    b = tenant_repo.create_tenant("B")
    geo = geo_repo.create(owner_id=a["id"], profile=sample_geo())

    monitor = monitor_repo.create(
        owner_id=a["id"],
        name="Walking Pad",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0AAA11111", "b0bbb22222"],
        geo_profile_ids=[geo["id"]],
        search_depth=100,
        provider_mode="managed",
    )

    loaded = monitor_repo.get(monitor["id"], owner_id=a["id"])
    assert loaded["asins"] == ["B0AAA11111", "B0BBB22222"]
    assert loaded["geo_profile_ids"] == [geo["id"]]
    assert monitor_repo.get(monitor["id"], owner_id=b["id"]) is None
