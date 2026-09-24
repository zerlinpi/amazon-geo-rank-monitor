from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class FakeStripeBilling:
    def __init__(self) -> None:
        self.checkout_calls = []
        self.webhook_calls = []

    def create_checkout(self, *, owner_id, credit_pack_id):
        self.checkout_calls.append((owner_id, credit_pack_id))
        return {
            "payment_id": "payment-1",
            "checkout_session_id": "cs_test_1",
            "checkout_url": "https://checkout.test/1",
        }

    def process_webhook(self, *, payload, signature):
        self.webhook_calls.append((payload, signature))
        return {"processed": True, "credited": True}


def setup_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    billing = BillingRepository(engine)
    billing.upsert_credit_pack(
        pack_id="starter",
        name="Starter Credits",
        credits=500,
        amount_minor=1000,
    )
    stripe = FakeStripeBilling()
    app = create_app(
        AppServices(
            tenant_repository=tenants,
            geo_repository=None,
            monitor_repository=None,
            job_repository=None,
            rank_repository=None,
            api_keys=keys,
            provider_registry=None,
            billing_repository=billing,
            stripe_billing=stripe,
        )
    )
    tenant = tenants.create_tenant("A")
    key = keys.create(owner_id=tenant["id"], name="test")
    return TestClient(app), tenant, {"X-API-Key": key.plaintext}, billing, stripe


def test_credit_balance_ledger_and_packs_are_tenant_authenticated() -> None:
    client, tenant, auth, billing, _ = setup_client()
    billing.grant(
        owner_id=tenant["id"],
        credits=50,
        idempotency_key="promo:1",
        entry_type="promotional_grant",
    )
    assert client.get("/api/v1/credits").status_code == 401
    balance = client.get("/api/v1/credits", headers=auth)
    assert balance.json()["available"] == 50
    ledger = client.get("/api/v1/credits/ledger", headers=auth)
    assert ledger.json()[0]["entry_type"] == "promotional_grant"
    packs = client.get("/api/v1/billing/packs", headers=auth)
    assert packs.json()[0]["id"] == "starter"


def test_checkout_uses_authenticated_tenant() -> None:
    client, tenant, auth, _, stripe = setup_client()
    response = client.post(
        "/api/v1/billing/checkout",
        headers=auth,
        json={"credit_pack_id": "starter"},
    )
    assert response.status_code == 201
    assert stripe.checkout_calls == [(tenant["id"], "starter")]


def test_webhook_is_signature_routed_without_api_key() -> None:
    client, _, _, _, stripe = setup_client()
    response = client.post(
        "/api/v1/billing/webhook",
        content=b"raw-event",
        headers={"Stripe-Signature": "sig"},
    )
    assert response.status_code == 200
    assert stripe.webhook_calls == [(b"raw-event", "sig")]
