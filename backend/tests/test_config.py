from pathlib import Path

import pytest
from pydantic import ValidationError

from amazon_geo_rank_monitor.config import AppSettings, build_oxylabs_provider, load_geo_profiles
from amazon_geo_rank_monitor.domain.errors import ConfigurationError


def test_load_geo_profiles_keeps_ip_and_delivery_locations_separate(tmp_path: Path) -> None:
    config = tmp_path / "geo.yaml"
    config.write_text(
        """geo_profiles:
  - id: us-ny-10001
    name: New York
    marketplace: amazon.com
    ip_country: US
    ip_state: NY
    ip_city: New York
    ip_postal_code: "10001"
    delivery_country: US
    delivery_postal_code: "11201"
    device: desktop
    weight: 3
"""
    )
    profiles = load_geo_profiles(config)
    assert len(profiles) == 1
    assert profiles[0].ip_postal_code == "10001"
    assert profiles[0].delivery_postal_code == "11201"
    assert str(profiles[0].weight) == "3"


def test_geo_weights_do_not_need_to_sum_to_one_hundred(tmp_path: Path) -> None:
    config = tmp_path / "geo.yaml"
    config.write_text(
        """geo_profiles:
  - id: ny
    name: NY
    marketplace: amazon.com
    ip_country: US
    delivery_country: US
    delivery_postal_code: "10001"
    weight: 3
  - id: la
    name: LA
    marketplace: amazon.com
    ip_country: US
    delivery_country: US
    delivery_postal_code: "90001"
    weight: 7
"""
    )
    profiles = load_geo_profiles(config)
    assert [str(p.weight) for p in profiles] == ["3", "7"]


def test_zero_weight_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "geo.yaml"
    config.write_text(
        """geo_profiles:
  - id: ny
    name: NY
    marketplace: amazon.com
    ip_country: US
    delivery_country: US
    delivery_postal_code: "10001"
    weight: 0
"""
    )
    with pytest.raises(ValidationError):
        load_geo_profiles(config)


def test_missing_oxylabs_credentials_only_fail_when_provider_is_built() -> None:
    settings = AppSettings(_env_file=None, oxylabs_username=None, oxylabs_password=None)
    assert settings.oxylabs_username is None
    with pytest.raises(ConfigurationError):
        build_oxylabs_provider(settings)
