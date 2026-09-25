from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

import pyotp
from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class MfaEnrollment:
    secret: str
    encrypted_secret: str
    provisioning_uri: str


class MfaCrypto:
    def __init__(self, *, encryption_key: str, issuer: str) -> None:
        if not encryption_key:
            raise ValueError("MFA encryption key is required")
        digest = hashlib.sha256(encryption_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._issuer = issuer.strip() or "Amazon Geo Rank Monitor"

    def begin_enrollment(self, *, email: str) -> MfaEnrollment:
        secret = pyotp.random_base32()
        return MfaEnrollment(
            secret=secret,
            encrypted_secret=self.encrypt_secret(secret),
            provisioning_uri=pyotp.TOTP(secret).provisioning_uri(
                name=email,
                issuer_name=self._issuer,
            ),
        )

    def encrypt_secret(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode()).decode()

    def decrypt_secret(self, encrypted_secret: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_secret.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("MFA secret cannot be decrypted") from exc

    def verify_totp(self, *, encrypted_secret: str, code: str) -> bool:
        normalized = "".join(ch for ch in code if ch.isdigit())
        if len(normalized) != 6:
            return False
        secret = self.decrypt_secret(encrypted_secret)
        return bool(pyotp.TOTP(secret).verify(normalized, valid_window=1))


def generate_recovery_codes(count: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_mfa_challenge_token() -> str:
    return f"agrmfa_{secrets.token_urlsafe(32)}"


def new_trusted_device_token() -> str:
    return f"agrd_{secrets.token_urlsafe(32)}"
