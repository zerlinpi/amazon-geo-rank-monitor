from uuid import UUID

import pytest
from test_api_hardening import auth_for, build_client, geo_payload


def test_browser_geo_payload_without_id_gets_unique_tenant_owned_ids():
    client, _, tenants, keys = build_client()
    owner, auth = auth_for(tenants, keys, "Browser")
    _, other_auth = auth_for(tenants, keys, "Other")
    payload = geo_payload()
    del payload["id"]

    first = client.post("/api/v1/geo-profiles", headers=auth, json=payload)
    second = client.post("/api/v1/geo-profiles", headers=auth, json=payload)
    assert first.status_code == second.status_code == 201
    rows = [first.json(), second.json()]
    assert rows[0]["id"] != rows[1]["id"]
    for row in rows:
        assert UUID(row["id"])
        assert row["owner_id"] == owner["id"]
    assert client.get("/api/v1/geo-profiles", headers=auth).json() == rows
    assert client.get("/api/v1/geo-profiles", headers=other_auth).json() == []


@pytest.mark.parametrize("changes", [{"name": " "}, {"weight": 0}, {"delivery_postal_code": ""}])
def test_browser_geo_payload_keeps_domain_validation(changes):
    client, _, tenants, keys = build_client()
    _, auth = auth_for(tenants, keys, "Browser")
    payload = geo_payload() | changes
    del payload["id"]
    response = client.post("/api/v1/geo-profiles", headers=auth, json=payload)
    assert response.status_code == 422
    assert client.get("/api/v1/geo-profiles", headers=auth).json() == []
