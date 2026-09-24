from __future__ import annotations

from typing import Any

from stripe import StripeClient

from amazon_geo_rank_monitor.domain.errors import ConfigurationError


class StripeGateway:
    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        client: Any | None = None,
    ) -> None:
        if not secret_key or not webhook_secret:
            raise ConfigurationError(
                "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required"
            )
        self._webhook_secret = webhook_secret
        self._client = client or StripeClient(secret_key)

    def create_checkout_session(
        self,
        *,
        mode: str,
        price_id: str,
        quantity: int,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> dict:
        session = self._client.v1.checkout.sessions.create(
            params={
                "mode": mode,
                "line_items": [
                    {
                        "price": price_id,
                        "quantity": quantity,
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
            },
            options={"idempotency_key": idempotency_key},
        )
        return {
            "id": session.id,
            "url": session.url,
        }

    def construct_event(self, payload: bytes, signature: str) -> dict:
        event = self._client.construct_event(
            payload,
            signature,
            self._webhook_secret,
        )
        if hasattr(event, "to_dict"):
            return event.to_dict(for_json=True)
        return dict(event)
