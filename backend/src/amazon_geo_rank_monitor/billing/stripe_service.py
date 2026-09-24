from __future__ import annotations


class StripeBillingService:
    PAID_EVENT_TYPES = {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }

    def __init__(
        self,
        *,
        repository,
        gateway,
        success_url: str,
        cancel_url: str,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._success_url = success_url
        self._cancel_url = cancel_url

    def create_checkout(
        self,
        *,
        owner_id: str,
        credit_pack_id: str,
    ) -> dict:
        pack = self._repository.get_credit_pack(
            credit_pack_id,
            active_only=True,
        )
        if pack is None:
            raise KeyError(f"credit pack not found: {credit_pack_id}")

        payment = self._repository.create_payment(
            owner_id=owner_id,
            credit_pack_id=credit_pack_id,
        )
        try:
            checkout = self._gateway.create_checkout_session(
                mode="payment",
                price_id=pack["stripe_price_id"],
                quantity=1,
                success_url=self._success_url,
                cancel_url=self._cancel_url,
                metadata={
                    "owner_id": owner_id,
                    "credit_pack_id": credit_pack_id,
                    "payment_id": payment["id"],
                },
                idempotency_key=payment["idempotency_key"],
            )
        except Exception:
            self._repository.mark_payment_failed(payment["id"])
            raise

        self._repository.attach_checkout_session(
            payment["id"],
            session_id=checkout["id"],
        )
        return {
            "payment_id": payment["id"],
            "session_id": checkout["id"],
            "url": checkout["url"],
        }

    def handle_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> dict:
        event = self._gateway.construct_event(payload, signature)
        event_id = str(event["id"])
        event_type = str(event["type"])

        if self._repository.webhook_event_exists(
            provider="stripe",
            event_id=event_id,
        ):
            return {
                "processed": True,
                "duplicate": True,
                "credits_granted": 0,
            }

        credits_granted = 0
        if event_type in self.PAID_EVENT_TYPES:
            checkout = event["data"]["object"]
            is_paid = (
                event_type == "checkout.session.async_payment_succeeded"
                or checkout.get("payment_status") == "paid"
            )
            if is_paid:
                payment = self._repository.get_payment_by_checkout_session(
                    str(checkout["id"])
                )
                if payment is None:
                    metadata = checkout.get("metadata") or {}
                    payment_id = metadata.get("payment_id")
                    if not payment_id:
                        raise KeyError("Stripe checkout is not linked to a payment")
                    payment = self._repository.get_payment(str(payment_id))

                pack = self._repository.get_credit_pack(
                    payment["credit_pack_id"],
                    active_only=False,
                )
                if pack is None:
                    raise KeyError(
                        f"credit pack not found: {payment['credit_pack_id']}"
                    )

                self._repository.grant(
                    owner_id=payment["owner_id"],
                    amount=pack["credits"],
                    idempotency_key=f"stripe-payment:{payment['id']}",
                    reference_type="payment",
                    reference_id=payment["id"],
                    metadata={
                        "stripe_event_id": event_id,
                        "credit_pack_id": pack["id"],
                    },
                )
                self._repository.mark_payment_paid(
                    payment["id"],
                    payment_intent_id=checkout.get("payment_intent"),
                )
                credits_granted = pack["credits"]

        self._repository.record_webhook_event(
            provider="stripe",
            event_id=event_id,
            event_type=event_type,
        )
        return {
            "processed": True,
            "duplicate": False,
            "credits_granted": credits_granted,
        }
