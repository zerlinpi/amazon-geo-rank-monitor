from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event
from test_api import create_auth, setup_client

from amazon_geo_rank_monitor.domain.models import RankObservation, RankSnapshot
from amazon_geo_rank_monitor.repositories.models import RankRunRow


@pytest.fixture
def history():
    client, tenants, keys = setup_client()
    tenant, auth = create_auth(tenants, keys, "History")
    other, other_auth = create_auth(tenants, keys, "Other")
    ranks = client.app.state.services.rank_repository
    yield client, ranks, tenant["id"], auth, other["id"], other_auth, keys
    client.close()


def seed_run(ranks, owner_id, number, *, keyword="trailer hitch", status="succeeded"):
    run_id = str(UUID(int=number))
    with ranks._sessions.begin() as session:
        session.add(RankRunRow(
            id=run_id,
            owner_id=owner_id,
            marketplace="amazon.com",
            keyword=keyword,
            status=status,
            requested_probe_count=1,
            started_at=datetime(2026, 9, 28, tzinfo=UTC),
            verification_metadata={
                "auto_strict_enabled": True,
                "strict_requested_count": 1,
                "strict_succeeded_count": 1,
                "events": [{"geo_profile_id": "ny", "triggers": ["manual_force"]}],
                "daily_budget_status": {"limit": 50},
            },
        ))
    return run_id


def test_pages_reach_older_runs_with_ties_and_concurrent_insertion(history):
    client, ranks, owner, auth, other, _, _ = history
    expected = [seed_run(ranks, owner, i) for i in range(1, 106)][::-1]
    seed_run(ranks, other, 999)
    first = client.get("/api/v1/runs/page", headers=auth, params={"limit": 40})
    assert first.status_code == 200
    page = first.json()
    seen = [item["id"] for item in page["items"]]
    assert seen == expected[:40]
    newer = seed_run(ranks, owner, 106)
    with ranks._sessions.begin() as session:
        session.get(RankRunRow, newer).started_at += timedelta(seconds=1)
    while page["next_cursor"]:
        response = client.get("/api/v1/runs/page", headers=auth, params={
            "limit": 40, "cursor": page["next_cursor"],
        })
        assert response.status_code == 200
        page = response.json()
        seen.extend(item["id"] for item in page["items"])
    assert seen == expected
    assert page["next_cursor"] is None


def test_summary_omits_heavy_evidence_but_detail_and_legacy_keep_it(history):
    client, ranks, owner, auth, _, _, _ = history
    run_id = seed_run(ranks, owner, 1)
    ranks.save_snapshots(run_id, [RankSnapshot(
        asin="B0TARGET01", weighted_rank=5, found_weight=100, missing_weight=0, confidence=1,
    )])
    response = client.get("/api/v1/runs/page", headers=auth)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["snapshot_count"] == 1
    assert item["verification_metadata"]["strict_succeeded_count"] == 1
    assert "observations" not in item
    assert "snapshots" not in item
    assert "events" not in item["verification_metadata"]
    assert "daily_budget_status" not in item["verification_metadata"]
    detail = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert detail["snapshots"][0]["asin"] == "B0TARGET01"
    assert detail["verification_metadata"]["events"][0]["geo_profile_id"] == "ny"
    legacy = client.get("/api/v1/runs", headers=auth).json()
    assert isinstance(legacy, list)
    assert legacy[0] == detail


def test_combined_filters_are_case_insensitive_and_tenant_scoped(history):
    client, ranks, owner, auth, other, _, _ = history
    wanted = seed_run(ranks, owner, 1, keyword="Heavy TRAILER Hitch", status="failed")
    wrong_status = seed_run(ranks, owner, 2, keyword="Heavy TRAILER Hitch")
    wrong_keyword = seed_run(ranks, owner, 3, keyword="walking pad", status="failed")
    foreign = seed_run(ranks, other, 4, keyword="Heavy TRAILER Hitch", status="failed")
    seed_run(ranks, owner, 5, keyword="Heavy TRAILER Hitch", status="failed")
    for run_id in (wanted, wrong_status, wrong_keyword, foreign):
        ranks.save_observations(run_id, [RankObservation(
            asin="B0TARGET01", geo_profile_id="ny", provider="fake",
            verification_level="managed", status="upstream_timeout", found=False,
            effective_rank=101,
        )])
    response = client.get("/api/v1/runs/page", headers=auth, params={
        "keyword": " trailer ", "status": "failed", "asin": "b0target01",
    })
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [wanted]
    assert response.json()["items"][0]["snapshot_count"] == 0


def test_keyword_wildcards_are_literal_and_snapshot_asins_are_searchable(history):
    client, ranks, owner, auth, _, _, _ = history
    wanted = seed_run(ranks, owner, 1, keyword="100%_fit hitch")
    seed_run(ranks, owner, 2, keyword="100XXfit hitch")
    ranks.save_snapshots(wanted, [RankSnapshot(
        asin="B0TARGET01", weighted_rank=5, found_weight=100, missing_weight=0, confidence=1,
    )])
    response = client.get("/api/v1/runs/page", headers=auth, params={
        "keyword": "%_", "asin": "B0TARGET01",
    })
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [wanted]


def test_history_cursor_does_not_reveal_foreign_runs(history):
    client, ranks, owner, auth, other, _, _ = history
    foreign = seed_run(ranks, other, 1)
    seed_run(ranks, owner, 2)
    foreign_response = client.get("/api/v1/runs/page", headers=auth, params={"cursor": foreign})
    missing_response = client.get("/api/v1/runs/page", headers=auth, params={
        "cursor": str(UUID(int=99)),
    })
    assert foreign_response.status_code == missing_response.status_code == 422
    assert foreign_response.json()["detail"] == missing_response.json()["detail"]


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 101}, {"cursor": "broken"},
    {"status": "unknown"}, {"keyword": "x" * 513}, {"asin": "x" * 33},
])
def test_history_rejects_invalid_query(history, params):
    client, _, _, auth, _, _, _ = history
    assert client.get("/api/v1/runs/page", headers=auth, params=params).status_code == 422


def test_history_requires_rank_read_scope_and_handles_empty_results(history):
    client, _, owner, auth, _, _, keys = history
    assert client.get("/api/v1/runs/page").status_code == 401
    key = keys.create(owner_id=owner, name="restricted", scopes=["geo:read"])
    assert client.get("/api/v1/runs/page", headers={
        "X-API-Key": key.plaintext,
    }).status_code == 403
    response = client.get("/api/v1/runs/page", headers=auth)
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_summary_query_count_does_not_grow_per_run(history):
    _, ranks, owner, _, _, _, _ = history
    for i in range(1, 61):
        seed_run(ranks, owner, i)
    queries = []
    engine = ranks._sessions.kw["bind"]

    def record_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        page = ranks.list_run_page(owner_id=owner, limit=50)
        assert len(page["items"]) == 50
        assert len(queries) <= 2
        queries.clear()
        next_page = ranks.list_run_page(owner_id=owner, limit=50, cursor=page["next_cursor"])
        assert len(next_page["items"]) == 10
        assert len(queries) <= 3
    finally:
        event.remove(engine, "before_cursor_execute", record_query)


def test_time_range_normalizes_offsets_and_preserves_pagination(history):
    client, ranks, owner, auth, other, _, _ = history
    ids = [seed_run(ranks, owner, number) for number in range(1, 5)]
    seed_run(ranks, other, 99)
    with ranks._sessions.begin() as session:
        for hour, run_id in enumerate(ids):
            session.get(RankRunRow, run_id).started_at = datetime(
                2026, 9, 28, hour, tzinfo=UTC,
            )
    params = {
        "started_from": "2026-09-28T09:00:00+08:00",
        "started_until": "2026-09-27T22:00:00-04:00",
        "limit": 1,
        "keyword": "trailer",
        "status": "succeeded",
    }
    first = client.get("/api/v1/runs/page", headers=auth, params=params)
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [ids[2]]
    second = client.get("/api/v1/runs/page", headers=auth, params={
        **params, "cursor": first.json()["next_cursor"],
    })
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == [ids[1]]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize(("bounds", "expected"), [
    ({"started_from": "2026-09-28T01:00:00Z"}, [3, 2]),
    ({"started_until": "2026-09-28T01:00:00Z"}, [2, 1]),
    ({"started_from": "2026-09-28T01:00:00Z",
      "started_until": "2026-09-28T01:00:00Z"}, [2]),
    ({"started_from": "2026-09-29T00:00:00Z"}, []),
])
def test_time_range_supports_open_and_inclusive_bounds(history, bounds, expected):
    client, ranks, owner, auth, _, _, _ = history
    for number in range(1, 4):
        run_id = seed_run(ranks, owner, number)
        with ranks._sessions.begin() as session:
            session.get(RankRunRow, run_id).started_at = datetime(
                2026, 9, 28, number - 1, tzinfo=UTC,
            )
    response = client.get("/api/v1/runs/page", headers=auth, params=bounds)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(UUID(int=number)) for number in expected
    ]


@pytest.mark.parametrize("bounds", [
    {"started_from": "2026-09-28T03:00:00Z", "started_until": "2026-09-28T02:00:00Z"},
    {"started_from": "not-a-date"},
    {"started_until": "2026-09-28T02:00:00"},
    {"started_from": "2026-09-28"},
    {"started_from": "20260928"},
    {"started_until": "1790553600000"},
    {"started_from": "0001-01-01T00:00:00+14:00"},
    {"started_until": "9999-12-31T23:59:59-14:00"},
])
def test_time_range_rejects_ambiguous_or_invalid_bounds(history, bounds):
    client, _, _, auth, _, _, _ = history
    assert client.get("/api/v1/runs/page", headers=auth, params=bounds).status_code == 422


def test_run_summaries_serialize_explicit_utc_timestamps(history):
    client, ranks, owner, auth, _, _, _ = history
    run_id = seed_run(ranks, owner, 1)
    with ranks._sessions.begin() as session:
        session.get(RankRunRow, run_id).completed_at = datetime(2026, 9, 28, 1, tzinfo=UTC)
    item = client.get("/api/v1/runs/page", headers=auth).json()["items"][0]
    assert datetime.fromisoformat(item["started_at"]) == datetime(2026, 9, 28, tzinfo=UTC)
    assert datetime.fromisoformat(item["completed_at"]) == datetime(2026, 9, 28, 1, tzinfo=UTC)
