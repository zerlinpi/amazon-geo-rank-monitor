from amazon_geo_rank_monitor.domain.models import GeoVerificationResult, ProxyLocation


def test_geo_verification_requires_both_ip_and_delivery_confirmation() -> None:
    result = GeoVerificationResult(
        requested_ip_country="US",
        requested_ip_state="NY",
        requested_ip_city="New York",
        requested_ip_postal_code="10001",
        observed_ip=ProxyLocation(
            ip="203.0.113.10",
            country="US",
            state="NY",
            city="New York",
            postal_code="10001",
        ),
        requested_delivery_postal_code="10001",
        confirmed_delivery_postal_code="10001",
    )
    assert result.ip_verified is True
    assert result.delivery_verified is True
    assert result.strict_verified is True


def test_geo_verification_fails_on_requested_ip_postal_mismatch() -> None:
    result = GeoVerificationResult(
        requested_ip_country="US",
        requested_ip_postal_code="10001",
        observed_ip=ProxyLocation(country="US", postal_code="90001"),
        requested_delivery_postal_code="10001",
        confirmed_delivery_postal_code="10001",
    )
    assert result.ip_verified is False
    assert result.strict_verified is False


def test_geo_verification_fails_when_delivery_zip_is_not_confirmed() -> None:
    result = GeoVerificationResult(
        requested_ip_country="US",
        observed_ip=ProxyLocation(country="US"),
        requested_delivery_postal_code="10001",
        confirmed_delivery_postal_code=None,
    )
    assert result.ip_verified is True
    assert result.delivery_verified is False
    assert result.strict_verified is False


def test_ip_zip_verification_does_not_require_less_reliable_state_city_fields() -> None:
    result = GeoVerificationResult(
        requested_ip_country="US",
        requested_ip_state="NY",
        requested_ip_city="New York",
        requested_ip_postal_code="10001",
        observed_ip=ProxyLocation(country="US", postal_code="10001"),
        requested_delivery_postal_code="10001",
        confirmed_delivery_postal_code="10001",
    )
    assert result.ip_verified is True
