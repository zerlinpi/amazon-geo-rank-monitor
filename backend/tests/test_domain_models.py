from decimal import Decimal

import pytest
from pydantic import ValidationError

from amazon_geo_rank_monitor.domain.models import GeoProfile, RankCheckRequest


def make_geo(weight: Decimal = Decimal("30")) -> GeoProfile:
    return GeoProfile(
        id="us-ny-10001",
        name="New York",
        marketplace="amazon.com",
        ip_country="US",
        ip_postal_code="10001",
        delivery_country="US",
        delivery_postal_code="10001",
        device="desktop",
        weight=weight,
    )


def test_geo_profile_requires_positive_weight() -> None:
    with pytest.raises(ValidationError):
        make_geo(Decimal("0"))


def test_rank_request_deduplicates_asins_preserving_order() -> None:
    request = RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=[" b0aaa11111 ", "B0AAA11111", "b0bbb22222"],
        geo_profiles=[make_geo()],
        search_depth=100,
    )
    assert request.asins == ["B0AAA11111", "B0BBB22222"]


def test_rank_request_rejects_empty_geo_profiles() -> None:
    with pytest.raises(ValidationError):
        RankCheckRequest(
            marketplace="amazon.com",
            keyword="walking pad",
            asins=["B0AAA11111"],
            geo_profiles=[],
            search_depth=100,
        )


def test_rank_request_rejects_blank_keyword() -> None:
    with pytest.raises(ValidationError):
        RankCheckRequest(
            marketplace="amazon.com",
            keyword="  ",
            asins=["B0AAA11111"],
            geo_profiles=[make_geo()],
            search_depth=100,
        )
