from sqlalchemy import create_engine

from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


def test_wrong_key_does_not_authenticate() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = TenantRepository(engine)
    tenant = repository.create_tenant("Acme")
    service = ApiKeyService(repository=repository, pepper="pepper")
    service.create(owner_id=tenant["id"], name="default")

    assert service.authenticate("agrm_not-the-key") is None
