import json
import sys

import pytest
from sqlalchemy import create_engine

from amazon_geo_rank_monitor import main
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.models import (
    Base,
    CreditAccountRow,
    TenantRow,
    UserRow,
    WorkspaceMembershipRow,
)


@pytest.fixture
def billing(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'credits.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(TenantRow.__table__.insert(), [
            {"id": "owner", "name": "First workspace"},
            {"id": "other", "name": "Other workspace"},
        ])
    yield BillingRepository(engine), engine
    engine.dispose()


def adjust(repo, **kwargs):
    values = dict(owner_id="owner", delta=50, operator="operator", reason="Trial allowance",
                  request_id="trial-1", apply=True)
    values.update(kwargs)
    return repo.adjust_balance(**values)


def test_adjustment_preview_does_not_change_balance_or_ledger(billing):
    repo, _ = billing
    result = adjust(repo, apply=False)
    assert result["applied"] is False
    assert result["balance_after"] == 50
    assert repo.get_balance("owner")["balance"] == 0
    assert repo.list_ledger(owner_id="owner") == []


def test_adjustment_is_audited_idempotent_and_scoped_to_one_workspace(billing):
    repo, _ = billing
    adjust(repo)
    adjust(repo)
    assert repo.get_balance("owner")["balance"] == 50
    assert repo.get_balance("other")["balance"] == 0
    entries = repo.list_ledger(owner_id="owner")
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "admin_adjustment"
    assert entries[0]["delta_credits"] == 50
    assert entries[0]["details"] == {
        "operator": "operator", "reason": "Trial allowance", "mode": "delta", "value": 50,
    }
    with pytest.raises(ValueError, match="request"):
        adjust(repo, delta=100)
    with pytest.raises(ValueError, match="request"):
        adjust(repo, owner_id="other")
    with pytest.raises(ValueError, match="request"):
        adjust(repo, reason="Changed reason")


def test_set_balance_replay_does_not_erase_subsequent_spending(billing):
    repo, _ = billing
    adjust(repo, delta=None, balance=100)
    reservation = repo.reserve(owner_id="owner", credits=5, idempotency_key="run",
                               reference_type="rank_check", reference_id="run")
    repo.settle(reservation["id"], credits_used=5)
    adjust(repo, delta=None, balance=100)
    assert repo.get_balance("owner")["balance"] == 95
    adjust(repo, delta=-20, request_id="correction")
    assert repo.get_balance("owner")["balance"] == 75


@pytest.mark.parametrize("update", [{"delta": -46}, {"delta": None, "balance": 4}])
def test_adjustment_cannot_spend_reserved_credits(billing, update):
    repo, _ = billing
    adjust(repo)
    reservation = repo.reserve(owner_id="owner", credits=5, idempotency_key="run",
                               reference_type="rank_check", reference_id="run")
    with pytest.raises(ValueError, match="reserved"):
        adjust(repo, request_id="decrease", **update)
    assert repo.get_balance("owner") == {"balance": 50, "reserved": 5, "available": 45}
    repo.settle(reservation["id"], credits_used=5)
    assert repo.get_balance("owner")["balance"] == 45


@pytest.mark.parametrize("update", [
    {"owner_id": "missing"}, {"reason": " "}, {"operator": " "}, {"request_id": " "},
    {"delta": -1}, {"delta": 2**31}, {"delta": True}, {"balance": 50},
])
def test_invalid_adjustment_leaves_no_ledger_or_balance_change(billing, update):
    repo, _ = billing
    with pytest.raises((ValueError, KeyError)):
        adjust(repo, **update)
    assert repo.get_balance("owner")["balance"] == 0
    assert repo.list_ledger(owner_id="owner") == []


def test_credit_cli_previews_applies_and_reports_target(billing, monkeypatch, capsys):
    repo, engine = billing
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    args = ["agrm-credits", "adjust", "--workspace", "owner", "--set-balance", "80",
            "--reason", "Initial allowance", "--operator", "owner", "--request-id", "first"]
    monkeypatch.setattr(sys, "argv", args)
    main.credits_main()
    preview = json.loads(capsys.readouterr().out)
    assert preview["workspace_name"] == "First workspace"
    assert preview["applied"] is False
    assert repo.get_balance("owner")["balance"] == 0
    monkeypatch.setattr(sys, "argv", [*args, "--apply"])
    main.credits_main()
    assert json.loads(capsys.readouterr().out)["applied"] is True
    assert repo.get_balance("owner")["balance"] == 80
    monkeypatch.setattr(sys, "argv", ["agrm-credits", "show", "--workspace", "owner"])
    main.credits_main()
    shown = json.loads(capsys.readouterr().out)
    assert shown["balance"] == 80
    assert shown["ledger"][0]["details"]["reason"] == "Initial allowance"


def test_credit_cli_finds_all_workspaces_for_exact_normalized_member_email(
    billing, monkeypatch, capsys,
):
    repo, engine = billing
    with engine.begin() as connection:
        connection.execute(TenantRow.__table__.insert(), {
            "id": "unrelated", "name": "Unrelated workspace",
        })
        connection.execute(UserRow.__table__.insert(), {
            "id": "member", "email": "owner@example.com", "password_hash": "test-only",
            "display_name": "Member",
        })
        connection.execute(WorkspaceMembershipRow.__table__.insert(), [
            {"id": "membership-1", "owner_id": "owner", "user_id": "member", "role": "owner"},
            {"id": "membership-2", "owner_id": "other", "user_id": "member", "role": "viewer"},
        ])
    adjust(repo, owner_id="other")
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setattr(sys, "argv", [
        "agrm-credits", "list", "--email", " OWNER@example.com ",
    ])
    main.credits_main()
    rows = json.loads(capsys.readouterr().out)
    assert [(row["workspace_id"], row["balance"]) for row in rows] == [
        ("owner", 0), ("other", 50),
    ]
    assert repo.list_accounts(email="missing@example.com") == []
    assert len(repo.list_accounts(limit=1)) == 1
    with engine.connect() as connection:
        # Read-only discovery must not create missing credit accounts.
        assert connection.execute(CreditAccountRow.__table__.select()).scalars().all() == ["other"]
    assert repo.list_ledger(owner_id="owner") == []
