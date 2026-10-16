import pytest

from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.runtime import build_services


def test_runtime_builds_without_provider_credentials() -> None:
    settings = AppSettings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper="test-pepper",
        oxylabs_username=None,
        oxylabs_password=None,
        residential_proxy_username=None,
        residential_proxy_password=None,
    )
    services = build_services(settings)
    tenant = services.tenant_repository.create_tenant("Acme")
    created = services.api_keys.create(owner_id=tenant["id"], name="default")
    assert services.api_keys.authenticate(created.plaintext) == tenant["id"]


@pytest.mark.asyncio
async def test_unconfigured_provider_fails_only_when_used() -> None:
    settings = AppSettings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper="test-pepper",
        oxylabs_username=None,
        oxylabs_password=None,
    )
    services = build_services(settings)
    provider = services.provider_registry.get("managed")

    with pytest.raises(ConfigurationError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=None,
            device="desktop",
            search_depth=100,
        )


def test_runtime_requires_api_key_pepper() -> None:
    settings = AppSettings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper=None,
    )
    with pytest.raises(ConfigurationError):
        build_services(settings)


@pytest.mark.parametrize("mode, costs", [(None, (0, 0)), ("free", (0, 0)), ("prepaid", (2, 7))])
def test_runtime_billing_mode_controls_all_rate_cards(mode, costs):
    kwargs = {} if mode is None else {"billing_mode": mode}
    services = build_services(AppSettings(
        _env_file=None, database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper="test", managed_serp_credit_cost=2, strict_serp_credit_cost=7, **kwargs,
    ))
    assert (services.rate_card.quote("managed", 1), services.rate_card.quote("strict", 1)) == costs
    assert services.auto_strict_verifier._rate_card == services.rate_card
