from sqlalchemy import create_engine

from amazon_geo_rank_monitor.billing.stripe_service import StripeBillingService
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import Base, TenantRow


class FakeGateway:
    def __init__(self) -> None:
        self.created = []
        self.event = None

    def create_checkout_session(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "cs_test_1", "url": "https://checkout.test/session"}

    def construct_event(self, payload, signature, secret):
        assert signature == "sig"
        assert secret == "whsec_test"
        return self.event


def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            TenantRow.__table__.insert().values(id="tenant-1", name="Tenant")
        )
    repo = BillingRepository(engine)
    repo.upsert_credit_pack(
        pack_id="starter",
        name="Starter Credits",
        credits=500,
        amount_minor=1000,
        currency="usd",
    )
    gateway = FakeGateway()
    service = StripeBillingService(
        repository=repo,
        secret_key="sk_test",
        webhook_secret="whsec_test",
        success_url="https://app.test/billing/success",
        cancel_url="https://app.test/billing",
        gateway=gateway,
    )
    return repo, gateway, service


def test_checkout_uses_server_side_pack_values() -> None:
    repo, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-1",
        credit_pack_id="starter",
    )
    assert checkout["checkout_session_id"] == "cs_test_1"
    request = gateway.created[0]
    assert request["mode"] == "payment"
    assert request["line_items"][0]["price_data"]["unit_amount"] == 1000
    assert request["metadata"]["tenant_id"] == "tenant-1"
    payment = repo.get_payment(checkout["payment_id"], owner_id="tenant-1")
    assert payment["credits"] == 500
    assert payment["status"] == "pending"


def test_paid_webhook_grants_credits_once() -> None:
    repo, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-1",
        credit_pack_id="starter",
    )
    gateway.event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "client_reference_id": checkout["payment_id"],
                "payment_status": "paid",
                "payment_intent": "pi_1",
                "metadata": {"payment_id": checkout["payment_id"]},
            }
        },
    }
    payload = b'{"event":"test"}'
    first = service.process_webhook(payload=payload, signature="sig")
    second = service.process_webhook(payload=payload, signature="sig")
    assert first["credited"] is True
    assert second["credited"] is True
    assert repo.get_balance("tenant-1")["balance"] == 500
    purchases = [
        entry
        for entry in repo.list_ledger(owner_id="tenant-1")
        if entry["entry_type"] == "purchase"
    ]
    assert len(purchases) == 1


def test_unpaid_completed_checkout_does_not_grant_credits() -> None:
    repo, gateway, service = setup()
    checkout = service.create_checkout(
        owner_id="tenant-1",
        credit_pack_id="starter",
    )
    gateway.event = {
        "id": "evt_unpaid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "client_reference_id": checkout["payment_id"],
                "payment_status": "unpaid",
                "metadata": {"payment_id": checkout["payment_id"]},
            }
        },
    }
    result = service.process_webhook(payload=b"unpaid", signature="sig")
    assert result["credited"] is False
    assert repo.get_balance("tenant-1")["balance"] == 0
