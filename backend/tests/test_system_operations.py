from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import SerpResult
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository
from amazon_geo_rank_monitor.repositories.worker_status_repository import (
    WorkerStatusRepository,
)


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult()


def build_system_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    jobs = JobRepository(engine, default_max_attempts=1)
    workers = WorkerStatusRepository(engine)
    rank_repository = RankRepository(engine)
    billing_repository = BillingRepository(engine)
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=jobs,
        rank_repository=rank_repository,
        api_keys=keys,
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
        billing_repository=billing_repository,
        rate_card=RateCard(managed_serp=1, browser_verified_serp=5),
        database_engine=engine,
        worker_status_repository=workers,
    )
    return (
        TestClient(create_app(services)),
        tenants,
        keys,
        jobs,
        workers,
        rank_repository,
        billing_repository,
    )


def test_system_queue_metrics_and_dead_letter_requeue_are_scoped() -> None:
    (
        client,
        tenants,
        keys,
        jobs,
        workers,
        rank_repository,
        billing_repository,
    ) = build_system_client()
    tenant = tenants.create_tenant("Acme")
    root = keys.create(owner_id=tenant["id"], name="root")
    reader = keys.create(
        owner_id=tenant["id"],
        name="ops reader",
        scopes=["system:read"],
    )
    root_headers = {"X-API-Key": root.plaintext}
    read_headers = {"X-API-Key": reader.plaintext}

    created = jobs.enqueue(
        owner_id=tenant["id"],
        provider_mode="managed",
        request_payload={"keyword": "walking pad"},
    )
    jobs.claim_one(worker_id="worker-a", lease_seconds=60)
    jobs.retry_or_dead_letter(created["id"], error="fatal")
    workers.heartbeat(
        worker_id="worker-a",
        status="dead_letter",
        last_job_id=created["id"],
        last_error="fatal",
        processed_delta=1,
    )
    cached_run_id = rank_repository.create_run(
        owner_id=tenant["id"],
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    rank_repository.complete_run(
        cached_run_id,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "strict_requested_count": 1,
            "strict_attempted_count": 0,
            "strict_succeeded_count": 1,
            "strict_skipped_count": 0,
            "events": [
                {
                    "geo_profile_id": "ny",
                    "requested": True,
                    "attempted": False,
                    "succeeded": True,
                    "cache_hit": True,
                    "triggers": ["rank_movement:B0TARGET01:25"],
                    "skipped_reason": None,
                    "error": None,
                }
            ],
        },
    )
    forced_run_id = rank_repository.create_run(
        owner_id=tenant["id"],
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    rank_repository.complete_run(
        forced_run_id,
        status="succeeded",
        settled_probe_count=2,
        verification_metadata={
            "manual_force_requested": True,
            "strict_requested_count": 1,
            "strict_attempted_count": 1,
            "strict_succeeded_count": 1,
            "strict_skipped_count": 0,
            "events": [
                {
                    "geo_profile_id": "la",
                    "requested": True,
                    "attempted": True,
                    "succeeded": True,
                    "cache_hit": False,
                    "triggers": ["manual_force", "managed_probe_failed"],
                    "skipped_reason": None,
                    "error": None,
                }
            ],
        },
    )
    skipped_run_id = rank_repository.create_run(
        owner_id=tenant["id"],
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
    )
    rank_repository.complete_run(
        skipped_run_id,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "strict_requested_count": 1,
            "strict_attempted_count": 0,
            "strict_succeeded_count": 0,
            "strict_skipped_count": 1,
            "events": [
                {
                    "geo_profile_id": "tx",
                    "requested": True,
                    "attempted": False,
                    "succeeded": False,
                    "cache_hit": False,
                    "triggers": ["low_confidence:0.50"],
                    "skipped_reason": "insufficient_credits",
                    "error": None,
                }
            ],
        },
    )

    billing_repository.grant(
        owner_id=tenant["id"],
        credits=20,
        idempotency_key="grant:verification-analytics",
    )
    strict_reservation = billing_repository.reserve(
        owner_id=tenant["id"],
        credits=5,
        idempotency_key="strict:forced-run",
        reference_type="auto_strict_verification",
        reference_id=forced_run_id,
    )
    billing_repository.settle(strict_reservation["id"], credits_used=5)
    other = tenants.create_tenant("Other")
    other_run_id = rank_repository.create_run(
        owner_id=other["id"],
        marketplace="amazon.com",
        keyword="desk treadmill",
        requested_probe_count=1,
    )
    rank_repository.complete_run(
        other_run_id,
        status="succeeded",
        settled_probe_count=1,
        verification_metadata={
            "strict_requested_count": 5,
            "strict_attempted_count": 5,
            "strict_succeeded_count": 4,
            "strict_skipped_count": 1,
        },
    )

    queue = client.get("/api/v1/system/queue", headers=read_headers)
    assert queue.status_code == 200
    assert queue.json()["counts"]["dead_letter"] == 1

    dead_letters = client.get(
        "/api/v1/system/dead-letters",
        headers=read_headers,
    )
    assert dead_letters.status_code == 200
    assert dead_letters.json()[0]["id"] == created["id"]

    verification = client.get(
        "/api/v1/system/verification-summary",
        headers=read_headers,
    )
    assert verification.status_code == 200
    assert verification.json() == {
        "strict_requested": 3,
        "strict_attempted": 1,
        "strict_succeeded": 2,
        "strict_skipped": 1,
    }

    analytics = client.get(
        "/api/v1/system/verification-analytics?hours=168",
        headers=read_headers,
    )
    assert analytics.status_code == 200
    analytics_body = analytics.json()
    assert analytics_body["run_count"] == 3
    assert analytics_body["strict_requested"] == 3
    assert analytics_body["strict_succeeded"] == 2
    assert analytics_body["strict_skipped"] == 1
    assert analytics_body["manual_requested"] == 1
    assert analytics_body["automatic_requested"] == 2
    assert analytics_body["cache_hits"] == 1
    assert analytics_body["recovered_failed_geos"] == 1
    assert analytics_body["success_rate_pct"] == 66.67
    assert analytics_body["skip_rate_pct"] == 33.33
    assert analytics_body["billing_available"] is True
    assert analytics_body["strict_credit_rate"] == 5
    assert analytics_body["billed_strict_probes"] == 1
    assert analytics_body["credits_spent"] == 5
    assert analytics_body["credits_per_success"] == 2.5
    assert analytics_body["estimated_cache_savings_credits"] == 5
    assert analytics_body["trigger_counts"] == {
        "low_confidence": 1,
        "managed_probe_failed": 1,
        "manual_force": 1,
        "rank_movement": 1,
    }
    assert analytics_body["skip_reason_counts"] == {
        "insufficient_credits": 1,
    }
    assert analytics_body["daily"][0]["credits_spent"] == 5

    metrics = client.get("/api/v1/system/metrics", headers=read_headers)
    assert metrics.status_code == 200
    assert 'agrm_rank_jobs{status="dead_letter"} 1' in metrics.text
    assert "agrm_service_heartbeat_age_seconds" in metrics.text
    assert "agrm_service_processed_jobs_total" in metrics.text
    assert (
        'agrm_auto_strict_verification_total{outcome="requested"} 3'
        in metrics.text
    )
    assert (
        'agrm_auto_strict_verification_total{outcome="succeeded"} 2'
        in metrics.text
    )
    assert (
        'agrm_auto_strict_verification_total{outcome="skipped"} 1'
        in metrics.text
    )

    denied = client.post(
        f"/api/v1/system/dead-letters/{created['id']}/requeue",
        headers=read_headers,
    )
    assert denied.status_code == 403

    requeued = client.post(
        f"/api/v1/system/dead-letters/{created['id']}/requeue",
        headers=root_headers,
    )
    assert requeued.status_code == 200
    assert requeued.json()["status"] == "pending"
    assert requeued.json()["attempt_count"] == 0


def test_system_operations_cannot_read_or_requeue_another_tenants_job():
    client, tenants, keys, jobs, workers, ranks, _ = build_system_client()
    victim = tenants.create_tenant("Victim")
    attacker = tenants.create_tenant("Other workspace owner")
    key = keys.create(owner_id=attacker["id"], name="owner")
    auth = {"X-API-Key": key.plaintext}
    job = jobs.enqueue(owner_id=victim["id"], provider_mode="managed",
                       request_payload={"keyword": "private-product"}, max_attempts=1)
    jobs.claim_one(worker_id="shared-worker")
    jobs.retry_or_dead_letter(job["id"], error="private-error", base_delay_seconds=0,
                              max_delay_seconds=0)
    workers.heartbeat(worker_id="shared-worker", status="idle", last_job_id=job["id"],
                       last_error="private-error")
    run = ranks.create_run(owner_id=victim["id"], marketplace="amazon.com", keyword="private",
                            requested_probe_count=1)
    ranks.complete_run(run, status="succeeded", settled_probe_count=1,
                       verification_metadata={"strict_requested_count": 9})
    assert client.get("/api/v1/system/dead-letters", headers=auth).json() == []
    assert client.get("/api/v1/system/queue", headers=auth).json()["counts"] == {}
    denied = client.post(f"/api/v1/system/dead-letters/{job['id']}/requeue", headers=auth)
    assert denied.status_code == 404
    assert jobs.get(job["id"], owner_id=victim["id"])["status"] == "dead_letter"
    state = client.get("/api/v1/system/workers", headers=auth).json()
    assert state[0]["last_job_id"] is None
    assert state[0]["last_error"] is None
    metrics = client.get("/api/v1/system/metrics", headers=auth).text
    assert 'agrm_auto_strict_verification_total{outcome="requested"} 0' in metrics
    assert 'agrm_rank_jobs{status="dead_letter"} 1' not in metrics


def test_strict_pacing_deferral_analytics_are_tenant_scoped() -> None:
    (
        client,
        tenants,
        keys,
        _jobs,
        _workers,
        ranks,
        _billing,
    ) = build_system_client()
    tenant = tenants.create_tenant("Pacing workspace")
    reader = keys.create(
        owner_id=tenant["id"],
        name="pacing reader",
        scopes=["system:read"],
    )
    headers = {"X-API-Key": reader.plaintext}

    initial = client.get(
        "/api/v1/system/verification-analytics?hours=24",
        headers=headers,
    )
    assert initial.status_code == 200
    assert initial.json()["pacing_deferred"] == 0
    assert initial.json()["pacing_deferral_rate_pct"] == 0.0

    def save_run(owner_id: str, *, triggers: list[str], reason: str | None):
        run_id = ranks.create_run(
            owner_id=owner_id,
            marketplace="amazon.com",
            keyword="towing hitch",
            requested_probe_count=1,
        )
        ranks.complete_run(
            run_id,
            status="succeeded",
            settled_probe_count=1,
            verification_metadata={
                "strict_requested_count": 1,
                "strict_attempted_count": int(reason is None),
                "strict_succeeded_count": int(reason is None),
                "strict_skipped_count": int(reason is not None),
                "events": [{
                    "geo_profile_id": "us-ny",
                    "requested": True,
                    "attempted": reason is None,
                    "succeeded": reason is None,
                    "triggers": triggers,
                    "skipped_reason": reason,
                }],
            },
        )

    save_run(
        tenant["id"],
        triggers=["low_confidence:0.40"],
        reason="daily_budget_pacing_deferred",
    )
    save_run(
        tenant["id"],
        triggers=["low_confidence:0.42"],
        reason=None,
    )
    # Defensive exclusion: manual-force events are never counted as auto pacing.
    save_run(
        tenant["id"],
        triggers=["manual_force"],
        reason="daily_budget_pacing_deferred",
    )
    other = tenants.create_tenant("Other workspace")
    save_run(
        other["id"],
        triggers=["low_confidence:0.40"],
        reason="daily_budget_pacing_deferred",
    )

    response = client.get(
        "/api/v1/system/verification-analytics?hours=24",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_count"] == 3
    assert body["automatic_requested"] == 2
    assert body["manual_requested"] == 1
    assert body["pacing_deferred"] == 1
    assert body["pacing_deferral_rate_pct"] == 50.0
    assert body["skip_reason_counts"]["daily_budget_pacing_deferred"] == 2
    assert len(body["daily"]) == 1
    assert body["daily"][0]["pacing_deferred"] == 1
