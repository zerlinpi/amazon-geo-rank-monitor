from types import SimpleNamespace

from amazon_geo_rank_monitor.mcp.tools import RankMcpTools


class Billing:
    def get_balance(self, owner_id):
        return {"balance": 10, "reserved": 2, "available": 8, "owner": owner_id}


def test_mcp_credit_balance_is_read_only_tenant_scoped() -> None:
    tools = RankMcpTools(
        services=SimpleNamespace(billing_repository=Billing()),
        owner_id="tenant-1",
    )
    assert tools.get_credit_balance() == {
        "balance": 10,
        "reserved": 2,
        "available": 8,
        "owner": "tenant-1",
    }
