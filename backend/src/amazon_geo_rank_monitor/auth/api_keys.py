from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiKeyCreation:
    id: str
    plaintext: str
    prefix: str


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

    def create(self, *, owner_id: str, name: str) -> ApiKeyCreation:
        plaintext = f"agrm_{secrets.token_urlsafe(32)}"
        prefix = plaintext[:16]
        row = self._repository.create_api_key(
            owner_id=owner_id,
            name=name,
            prefix=prefix,
            key_hash=self._hash(plaintext),
        )
        return ApiKeyCreation(id=row["id"], plaintext=plaintext, prefix=prefix)

    def authenticate(self, plaintext: str) -> str | None:
        if not plaintext.startswith("agrm_"):
            return None
        prefix = plaintext[:16]
        row = self._repository.find_active_api_key_by_prefix(prefix)
        if row is None:
            return None
        if not hmac.compare_digest(row["key_hash"], self._hash(plaintext)):
            return None
        self._repository.touch_api_key(row["id"])
        return row["owner_id"]

    def revoke(self, key_id: str, *, owner_id: str) -> None:
        self._repository.revoke_api_key(key_id, owner_id=owner_id)
