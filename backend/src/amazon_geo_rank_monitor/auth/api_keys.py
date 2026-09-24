from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


ALLOWED_API_KEY_SCOPES = frozenset(
    {
        "*",
        "geo:read",
        "geo:write",
        "monitors:read",
        "monitors:write",
        "rank:read",
        "rank:write",
        "billing:read",
        "billing:write",
        "keys:manage",
        "system:read",
    }
)


@dataclass(frozen=True)
class ApiPrincipal:
    owner_id: str
    key_id: str
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


@dataclass(frozen=True)
class ApiKeyCreation:
    id: str
    plaintext: str
    prefix: str
    scopes: tuple[str, ...]


def normalize_scopes(scopes: list[str] | tuple[str, ...] | None) -> list[str]:
    requested = list(scopes or ["*"])
    normalized = list(dict.fromkeys(item.strip() for item in requested if item.strip()))
    if not normalized:
        raise ValueError("at least one API key scope is required")
    unknown = sorted(set(normalized) - ALLOWED_API_KEY_SCOPES)
    if unknown:
        raise ValueError(f"unsupported API key scopes: {', '.join(unknown)}")
    if "*" in normalized and len(normalized) > 1:
        return ["*"]
    return normalized


class ApiKeyService:
    def __init__(self, *, repository, pepper: str) -> None:
        if not pepper:
            raise ValueError("API key pepper must not be empty")
        self._repository = repository
        self._pepper = pepper.encode()

    def _hash(self, plaintext: str) -> str:
        return hmac.new(
            self._pepper,
            plaintext.encode(),
            hashlib.sha256,
        ).hexdigest()

    def create(
        self,
        *,
        owner_id: str,
        name: str,
        scopes: list[str] | tuple[str, ...] | None = None,
    ) -> ApiKeyCreation:
        normalized_scopes = normalize_scopes(scopes)
        plaintext = f"agrm_{secrets.token_urlsafe(32)}"
        prefix = plaintext[:16]
        row = self._repository.create_api_key(
            owner_id=owner_id,
            name=name,
            prefix=prefix,
            key_hash=self._hash(plaintext),
            scopes=normalized_scopes,
        )
        return ApiKeyCreation(
            id=row["id"],
            plaintext=plaintext,
            prefix=prefix,
            scopes=tuple(row["scopes"]),
        )

    def authenticate_principal(self, plaintext: str) -> ApiPrincipal | None:
        if not plaintext.startswith("agrm_"):
            return None
        prefix = plaintext[:16]
        row = self._repository.find_active_api_key_by_prefix(prefix)
        if row is None:
            return None
        if not hmac.compare_digest(row["key_hash"], self._hash(plaintext)):
            return None
        self._repository.touch_api_key(row["id"])
        return ApiPrincipal(
            owner_id=row["owner_id"],
            key_id=row["id"],
            scopes=frozenset(row.get("scopes") or ["*"]),
        )

    def authenticate(self, plaintext: str) -> str | None:
        principal = self.authenticate_principal(plaintext)
        return principal.owner_id if principal else None

    def revoke(self, key_id: str, *, owner_id: str) -> None:
        self._repository.revoke_api_key(key_id, owner_id=owner_id)
