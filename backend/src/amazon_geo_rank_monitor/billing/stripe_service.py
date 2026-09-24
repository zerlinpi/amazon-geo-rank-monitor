from __future__ import annotations

import hashlib
from typing import Any


class StripeGateway:
    def __init__(self, secret_key: str) -> None:
        import stripe

        stripe.api_key = secret_key
        self._stripe = stripe

    def create_checkout_session(self, **kwargs):
        return self._stripe.checkout.Session.create(**kwargs)

    def construct_event(self, payload: bytes, signature: str, secret: str):
        return self._stripe.Webhook.construct_event(payload, signature, secret)


class StripeBillingService:
    PAID_EVENTS = {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }

    def __init__(
        self,
        *,
        repository,
        secret_key: str,
        webhook_secret: str,
        success_url: str,
        cancel_url: str,
        gateway: Any | None = None,
    ) -> None:
        self._repository = repository
        self._webhook_secret = webhook_secret
        self._success_url = success_url
        self._cancel_url = cancel_url
        self._gateway = gateway or StripeGateway(secret_key)

    def create_checkout(self, *, owner_id: str, credit_pack_id: str) -> dict:
        pack = self._repository.get_credit_pack(credit_pack_id)
        payment = self._repository.create_payment(
            owner_id=owner_id,
            credit_pack_id=credit_pack_id,
        )
        metadata = {
            "payment_id": payment["id"],
            "tenant_id": owner_id,
            "credit_pack_id": credit_pack_id,
        }
        session = self._gateway.create_checkout_session(
            mode="payment",
            success_url=self._success_url,
            cancel_url=self._cancel_url,
            client_reference_id=payment["id"],
            metadata=metadata,
            payment_intent_data={"metadata": metadata},
            line_items=[
                {
                    "price_data": {
                        "currency": pack["currency"],
                        "unit_amount": pack["amount_minor"],
                        "product_data": {"name": pack["name"]},
                    },
                    "quantity": 1,
                }
            ],
        )
        session_id = self._value(session, "id")
        url = self._value(session, "url")
        self._repository.attach_payment_session(payment["id"], session_id=session_id)
        return {
            "payment_id": payment["id"],
            "checkout_session_id": session_id,
            "checkout_url": url,
        }

    def process_webhook(self, *, payload: bytes, signature: str) -> dict:
        event = self._gateway.construct_event(
            payload,
            signature,
            self._webhook_secret,
        )
        event_id = self._value(event, "id")
        event_type = self._value(event, "type")
        payload_hash = hashlib.sha256(payload).hexdigest()

        if event_type not in self.PAID_EVENTS:
            created = self._repository.record_webhook_event(
                provider_event_id=event_id,
                event_type=event_type,
                payload_hash=payload_hash,
            )
            return {"processed": created, "credited": False}

        session = self._nested(event, "data", "object")
        payment_status = self._value(session, "payment_status", default=None)
        if payment_status != "paid":
            created = self._repository.record_webhook_event(
                provider_event_id=event_id,
                event_type=event_type,
                payload_hash=payload_hash,
            )
            return {"processed": created, "credited": False}

        payment_id = (
            self._value(session, "client_reference_id", default=None)
            or self._nested(session, "metadata", "payment_id")
        )
        payment = self._repository.apply_paid_checkout(
            provider_event_id=event_id,
            event_type=event_type,
            payload_hash=payload_hash,
            payment_id=payment_id,
            session_id=self._value(session, "id"),
            payment_intent_id=self._value(
                session,
                "payment_intent",
                default=None,
            ),
        )
        return {"processed": True, "credited": True, "payment": payment}

    @staticmethod
    def _value(obj, key: str, *, default=...):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
        else:
            value = getattr(obj, key, default)
            if value is not default:
                return value
        if default is not ...:
            return default
        raise ValueError(f"Stripe object is missing {key}")

    @classmethod
    def _nested(cls, obj, *keys):
        current = obj
        for key in keys:
            current = cls._value(current, key)
        return current
