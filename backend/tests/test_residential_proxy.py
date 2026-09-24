from decimal import Decimal

import pytest

from amazon_geo_rank_monitor.config import (
    AppSettings,
    build_residential_proxy_factory,
)
from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.providers.residential_proxy import (
    OxylabsResidentialProxyFactory,
)


def geo() -> GeoProfile:
    return GeoProfile(
        id="us-ny-10001",
        name="New York",
        marketplace="amazon.com",
        ip_country="US",
        ip_state="NY",
        ip_city="New York",
        ip_postal_code="10001",
        delivery_country="US",
        delivery_postal_code="10001",
        device="desktop",
        weight=Decimal("1"),
    )


def test_proxy_factory_targets_country_zip_and_sticky_session() -> None:
    factory = OxylabsResidentialProxyFactory(
        username="rank-user",
        password="super-secret",
    )
    proxy = factory.build(geo(), session_id="strict-abc123")
    assert proxy.server == "http://pr.oxylabs.io:7777"
    assert proxy.username == (
        "customer-rank-user-cc-US-postalcode-10001-sessid-strict-abc123"
    )
    assert proxy.password.get_secret_value() == "super-secret"


def test_proxy_password_is_redacted_from_repr() -> None:
    proxy = OxylabsResidentialProxyFactory(
        username="rank-user",
        password="super-secret",
    ).build(geo(), session_id="strict-abc123")
    assert "super-secret" not in repr(proxy)
    assert "super-secret" not in str(proxy)


def test_missing_proxy_credentials_fail_when_factory_is_built() -> None:
    settings = AppSettings(
        _env_file=None,
        residential_proxy_username=None,
        residential_proxy_password=None,
    )
    with pytest.raises(ConfigurationError):
        build_residential_proxy_factory(settings)


def test_zip_targeting_rejects_non_us_country() -> None:
    profile = geo().model_copy(
        update={"ip_country": "GB", "ip_postal_code": "SW1A 1AA"}
    )
    factory = OxylabsResidentialProxyFactory(
        username="rank-user",
        password="secret",
    )
    with pytest.raises(ConfigurationError):
        factory.build(profile, session_id="strictabc")
