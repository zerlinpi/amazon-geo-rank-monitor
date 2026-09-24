from __future__ import annotations

from pydantic import BaseModel, SecretStr

from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import GeoProfile


class BrowserProxyConfig(BaseModel):
    server: str
    username: str
    password: SecretStr

    def to_playwright(self) -> dict[str, str]:
        return {
            "server": self.server,
            "username": self.username,
            "password": self.password.get_secret_value(),
        }


class OxylabsResidentialProxyFactory:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        server: str = "http://pr.oxylabs.io:7777",
    ) -> None:
        self._username = username.strip()
        self._password = password
        self._server = server

    def build(
        self,
        geo_profile: GeoProfile,
        *,
        session_id: str,
    ) -> BrowserProxyConfig:
        country = geo_profile.ip_country.upper()
        if geo_profile.ip_postal_code and country != "US":
            raise ConfigurationError(
                "Oxylabs residential ZIP targeting is currently US-only"
            )
        parts = [f"customer-{self._username}", f"cc-{country}"]
        if geo_profile.ip_postal_code:
            parts.append(f"postalcode-{geo_profile.ip_postal_code}")
        parts.append(f"sessid-{session_id}")
        return BrowserProxyConfig(
            server=self._server,
            username="-".join(parts),
            password=SecretStr(self._password),
        )
