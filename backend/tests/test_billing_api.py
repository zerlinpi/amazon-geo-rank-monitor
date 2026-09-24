from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class NullProvider:
    provider_name = "null"

    async def search(self, **kwargs):
        raise AssertionError("provider should not be called")


class FakeStripeBilling:
    def __init__(self) -> None:
        self.checkout_calls = []
        self.webhook_calls = []

    def create_checkout(self, *, owner_id: str, credit_pack_id: str) -> dict:
        self.checkout_calls.append((owner_id, credit_pack_id))
        return {
            "payment_id": "pay_1",
            "session_id": "cs_1",
            "url": "https://checkout.stripe.test/cs_1",
        }

    def handle_webhook(self, *, payload: bytes, signature: str) -> dict:
        if signature != "valid":
            raise ValueError("invalid signature")
        self.webhook_calls.append((payload, signature))
        return {
            "processed": True,
            "duplicate": False,
            "credits_granted": 500,
        }


def setup():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    billing = BillingRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    stripe_billing = FakeStripeBilling()
    provider = NullProvider()
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=RankRepository(engine),
        api_keys=keys,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
        billing_repository=billing,
        stripe_billing=stripe_billing,
    )
    return TestClient(create_app(services)), tenants, keys, billing, stripe_billing


def auth(tenants, keys, name="A"):
    tenant = tenants.create_tenant(name)
    key = keys.create(owner_id=tenant["id"], name="test")
    return tenant, {"X-API-Key": key.plaintext}


def test_credit_balance_and_ledger_are_tenant_scoped() -> None:
    client, tenants, keys, billing, _ = setup()
    tenant_a, auth_a = auth(tenants, keys, "A")
    _, auth_b = auth(tenants, keys, "B")
    billing.grant(
        owner_id=tenant_a["id"],
        amount=25,
        idempotency_key="grant-a",
        reference_type="test",
        reference_id="a",
    )

    balance_a = client.get("/api/v1/credits", headers=auth_a)
    balance_b = client.get("/api/v1/credits", headers=auth_b)
    ledger_a = client.get("/api/v1/credits/ledger", headers=auth_a)
    ledger_b = client.get("/api/v1/credits/ledger", headers=auth_b)

    assert balance_a.json()["available_credits"] == 25
    assert balance_b.json()["available_credits"] == 0
    assert len(ledger_a.json()) == 1
    assert ledger_b.json() == []


def test_pack_listing_hides_stripe_price_id() -> None:
    client, tenants, keys, billing, _ = setup()
    _, headers = auth(tenants, keys)
    billing.create_credit_pack(
        pack_id="starter",
        name="Starter",
        credits=500,
        stripe_price_id="price_secret_mapping",
    )

    response = client.get("/api/v1/billing/packs", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "starter",
            "name": "Starter",
            "credits": 500,
            "active": True,
            "display_order": 0,
        }
    ]


def test_checkout_accepts_only_server_owned_pack_identifier() -> None:
    client, tenants, keys, billing, stripe_billing = setup()
    tenant, headers = auth(tenants, keys)
    billing.create_credit_pack(
        pack_id="starter",
        name="Starter",
        credits=500,
        stripe_price_id="price_server",
    )

    response = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={"credit_pack_id": "starter"},
    )
    tampered = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={
            "credit_pack_id": "starter",
            "credits": 999999,
            "price_id": "price_attacker",
        },
    )

    assert response.status_code == 200
    assert stripe_billing.checkout_calls == [(tenant["id"], "starter")]
    assert tampered.status_code == 422


def test_webhook_uses_stripe_signature_not_saas_api_key() -> None:
    client, _, _, _, stripe_billing = setup()

    ok = client.post(
        "/api/v1/billing/webhook",
        content=b"raw-stripe-body",
        headers={"Stripe-Signature": "valid"},
    )
    missing = client.post(
        "/api/v1/billing/webhook",
        content=b"raw-stripe-body",
    )
    invalid = client.post(
        "/api/v1/billing/webhook",
        content=b"raw-stripe-body",
        headers={"Stripe-Signature": "wrong"},
    )

    assert ok.status_code == 200
    assert stripe_billing.webhook_calls == [(b"raw-stripe-body", "valid")]
    assert missing.status_code == 400
    assert invalid.status_code == 400
