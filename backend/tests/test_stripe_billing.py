from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.billing.stripe_service import StripeBillingService
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import Base


class FakeStripeGateway:
    def __init__(self) -> None:
        self.checkout_calls: list[dict] = []
        self.event: dict | None = None

    def create_checkout_session(self, **kwargs) -> dict:
        self.checkout_calls.append(kwargs)
        return {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.test/cs_test_123",
        }

    def construct_event(self, payload: bytes, signature: str) -> dict:
        assert payload == b"raw-body"
        assert signature == "valid-signature"
        if self.event is None:
            raise AssertionError("test must set gateway.event")
        return self.event


def setup():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    billing = BillingRepository(engine)
    billing.create_credit_pack(
        pack_id="starter",
        name="Starter",
        credits=500,
        stripe_price_id="price_server_owned",
        display_order=1,
    )
    gateway = FakeStripeGateway()
    service = StripeBillingService(
        repository=billing,
        gateway=gateway,
        success_url="https://app.example.com/billing/success",
        cancel_url="https://app.example.com/billing",
    )
    return billing, gateway, service


def test_checkout_uses_server_owned_pack_price_and_payment_mode() -> None:
    billing, gateway, service = setup()

    checkout = service.create_checkout(
        owner_id="tenant-a",
        credit_pack_id="starter",
    )

    assert checkout["session_id"] == "cs_test_123"
    assert checkout["url"].startswith("https://checkout.stripe.test/")
    call = gateway.checkout_calls[0]
    assert call["mode"] == "payment"
    assert call["price_id"] == "price_server_owned"
    assert call["quantity"] == 1
    assert call["metadata"]["owner_id"] == "tenant-a"
    assert call["metadata"]["credit_pack_id"] == "starter"
    assert call["metadata"]["payment_id"] == checkout["payment_id"]
    payment = billing.get_payment(checkout["payment_id"], owner_id="tenant-a")
    assert payment["status"] == "checkout_created"
    assert payment["stripe_checkout_session_id"] == "cs_test_123"


def test_paid_checkout_webhook_grants_pack_once_even_when_event_repeats() -> None:
    billing, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-a",
        credit_pack_id="starter",
    )
    gateway.event = {
        "id": "evt_paid_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": checkout["session_id"],
                "payment_status": "paid",
                "payment_intent": "pi_123",
                "metadata": {"payment_id": checkout["payment_id"]},
            }
        },
    }

    first = service.handle_webhook(
        payload=b"raw-body",
        signature="valid-signature",
    )
    second = service.handle_webhook(
        payload=b"raw-body",
        signature="valid-signature",
    )

    assert first["credits_granted"] == 500
    assert second["duplicate"] is True
    assert billing.get_account("tenant-a")["available_credits"] == 500
    ledger = billing.list_ledger(owner_id="tenant-a")
    assert len([e for e in ledger if e["entry_type"] == "purchase"]) == 1


def test_unpaid_checkout_completion_does_not_grant_credits() -> None:
    billing, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-a",
        credit_pack_id="starter",
    )
    gateway.event = {
        "id": "evt_unpaid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": checkout["session_id"],
                "payment_status": "unpaid",
                "metadata": {"payment_id": checkout["payment_id"]},
            }
        },
    }

    result = service.handle_webhook(
        payload=b"raw-body",
        signature="valid-signature",
    )

    assert result["credits_granted"] == 0
    assert billing.get_account("tenant-a")["available_credits"] == 0
    payment = billing.get_payment(checkout["payment_id"], owner_id="tenant-a")
    assert payment["status"] == "checkout_created"


def test_async_payment_succeeded_grants_same_server_owned_pack() -> None:
    billing, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-a",
        credit_pack_id="starter",
    )
    gateway.event = {
        "id": "evt_async_paid",
        "type": "checkout.session.async_payment_succeeded",
        "data": {
            "object": {
                "id": checkout["session_id"],
                "payment_status": "paid",
                "payment_intent": "pi_async",
                "metadata": {
                    "payment_id": checkout["payment_id"],
                    "credits": "999999",
                },
            }
        },
    }

    result = service.handle_webhook(
        payload=b"raw-body",
        signature="valid-signature",
    )

    assert result["credits_granted"] == 500
    assert billing.get_account("tenant-a")["available_credits"] == 500
