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


def test_runtime_builds_credit_meter_without_stripe_credentials() -> None:
    settings = AppSettings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper="test-pepper",
        managed_serp_credits=2,
        strict_serp_credits=7,
        stripe_secret_key=None,
        stripe_webhook_secret=None,
    )
    services = build_services(settings)

    assert services.billing_repository is not None
    assert services.usage_meter is not None
    assert services.stripe_billing is None
    assert services.usage_meter._rate_card.managed_serp_credits == 2
    assert services.usage_meter._rate_card.strict_serp_credits == 7


def test_runtime_seeds_credit_packs_from_server_configuration() -> None:
    settings = AppSettings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        api_key_pepper="test-pepper",
        credit_packs_json=(
            '[{"id":"starter","name":"Starter","credits":500,'
            '"stripe_price_id":"price_test_starter","display_order":1}]'
        ),
    )
    services = build_services(settings)

    packs = services.billing_repository.list_credit_packs()
    assert packs[0]["id"] == "starter"
    assert packs[0]["credits"] == 500
    assert packs[0]["stripe_price_id"] == "price_test_starter"
