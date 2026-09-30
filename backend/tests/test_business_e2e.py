from fastapi.testclient import TestClient
from offline_stack import build_offline_services, offline_worker
from sqlalchemy import func, select

from amazon_geo_rank_monitor.api.app import create_app
from amazon_geo_rank_monitor.repositories.models import SerpCompetitiveObservationRow


async def test_account_monitor_worker_history_analytics_and_cached_billing(tmp_path):
    services, provider = build_offline_services(f"sqlite+pysqlite:///{tmp_path / 'business.db'}")
    with TestClient(create_app(services, api_rate_limit_per_minute=1000)) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email": "business@example.com", "password": "offline-secure-password",
            "display_name": "Owner", "workspace_name": "Offline business",
        })
        assert registered.status_code == 201
        owner = registered.json()["workspace"]["id"]
        headers = {"X-CSRF-Token": client.cookies["agrm_csrf"]}
        services.billing_repository.grant(owner_id=owner, credits=100, idempotency_key="fixture")
        geo_ids = []
        for index, (postal, weight) in enumerate([("10001", 50), ("90001", 30), ("60601", 20)]):
            response = client.post("/api/v1/geo-profiles", headers=headers, json={
                "id": f"geo-{index}", "name": f"Region {index}", "marketplace": "amazon.com",
                "ip_country": "US", "ip_postal_code": postal, "delivery_country": "US",
                "delivery_postal_code": postal, "weight": weight,
            })
            assert response.status_code == 201
            geo_ids.append(response.json()["id"])
        response = client.post("/api/v1/monitors", headers=headers, json={
            "name": "Trailer hitch", "marketplace": "amazon.com", "keyword": "trailer hitch",
            "asins": ["B0TARGET01", "B0TARGET02"], "geo_profile_ids": geo_ids,
            "search_depth": 100, "provider_mode": "managed",
        })
        assert response.status_code == 201
        monitor_id = response.json()["id"]
        worker = offline_worker(services)
        run_ids = []
        for cached in [False, True]:
            queued = client.post(f"/api/v1/monitors/{monitor_id}/run", headers=headers)
            assert queued.status_code == 202
            completed = await worker.run_once()
            assert completed["status"] == "succeeded"
            run_ids.append(completed["run_id"])
            detail = client.get(f"/api/v1/runs/{completed['run_id']}").json()
            assert len(detail["observations"]) == 6
            assert {o["verification_level"] for o in detail["observations"]} == {"managed"}
            assert detail["cache_hit_count"] == (3 if cached else 0)
            assert detail["settled_probe_count"] == (0 if cached else 3)
            assert sorted(float(s["weighted_rank"]) for s in detail["snapshots"]) == [8.5, 9.5]
        assert provider.calls == 3  # Three geos, two ASINs, two runs: only three paid SERPs.
        assert services.billing_repository.get_balance(owner)["balance"] == 97
        page = client.get("/api/v1/runs/page", params={"asin": "B0TARGET02"}).json()
        assert {r["id"] for r in page["items"]} == set(run_ids)
        history = client.get(f"/api/v1/monitors/{monitor_id}/history").json()
        assert len(history) == 2
        summary = client.get(f"/api/v1/analytics/monitors/{monitor_id}/summary").json()
        assert summary["run_count"] == 2
        assert len(summary["geos"]) == 6
        assert all(g["observation_count"] == 2 for g in summary["geos"])
        with services.database_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(
                SerpCompetitiveObservationRow,
            )) > 0
    services.database_engine.dispose()
