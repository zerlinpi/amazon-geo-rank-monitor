from amazon_geo_rank_monitor.domain.models import (
    ProbeStatus,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)
from amazon_geo_rank_monitor.ranking.matcher import match_asins


def test_matches_organic_rank_independent_of_sponsored_results() -> None:
    result = SerpResult(
        organic_products=[
            SerpProduct(asin="B0AAA11111", position=4, page=1),
            SerpProduct(asin="B0TARGET01", position=7, page=1),
        ],
        sponsored_products=[
            SerpProduct(asin="B0TARGET01", position=1, page=1, sponsored=True),
        ],
    )
    observations = match_asins(
        result,
        ["B0TARGET01"],
        search_depth=100,
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
    )
    obs = observations[0]
    assert obs.organic_rank == 2
    assert obs.sponsored_rank == 1
    assert obs.absolute_rank == 7
    assert obs.effective_rank == 2
    assert obs.status == ProbeStatus.SUCCESS_FOUND


def test_missing_asin_uses_search_depth_plus_one() -> None:
    result = SerpResult(
        organic_products=[SerpProduct(asin="B0OTHER0001", position=1, page=1)]
    )
    obs = match_asins(
        result,
        ["B0MISSING01"],
        search_depth=100,
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
    )[0]
    assert obs.found is False
    assert obs.organic_rank is None
    assert obs.effective_rank == 101
    assert obs.status == ProbeStatus.SUCCESS_NOT_FOUND


def test_duplicate_asins_do_not_duplicate_observations() -> None:
    result = SerpResult(
        organic_products=[SerpProduct(asin="B0TARGET01", position=1, page=1)]
    )
    observations = match_asins(
        result,
        ["B0TARGET01", "b0target01"],
        search_depth=100,
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
    )
    assert len(observations) == 1


def test_organic_rank_at_search_depth_boundary_is_found() -> None:
    result = SerpResult(
        organic_products=[
            SerpProduct(asin=f"B0RANK{i:05d}", position=i + 3, page=(i - 1) // 20 + 1)
            for i in range(1, 102)
        ]
    )
    obs = match_asins(
        result,
        ["B0RANK00100"],
        search_depth=100,
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
    )[0]
    assert obs.status == ProbeStatus.SUCCESS_FOUND
    assert obs.found is True
    assert obs.organic_rank == 100
    assert obs.absolute_rank == 103
    assert obs.effective_rank == 100
    assert obs.page == 5


def test_organic_rank_beyond_depth_is_missing_even_when_sponsored() -> None:
    result = SerpResult(
        organic_products=[
            SerpProduct(asin=f"B0RANK{i:05d}", position=i + 3, page=(i - 1) // 20 + 1)
            for i in range(1, 102)
        ],
        sponsored_products=[
            SerpProduct(asin="B0RANK00101", position=1, page=1, sponsored=True)
        ],
    )
    obs = match_asins(
        result,
        ["B0RANK00101"],
        search_depth=100,
        geo_profile_id="us-ny-10001",
        provider="oxylabs",
        verification_level=VerificationLevel.MANAGED,
    )[0]
    assert obs.status == ProbeStatus.SUCCESS_NOT_FOUND
    assert obs.found is False
    assert obs.organic_rank is None
    assert obs.absolute_rank is None
    assert obs.sponsored_rank == 1
    assert obs.effective_rank == 101
    assert obs.page is None
