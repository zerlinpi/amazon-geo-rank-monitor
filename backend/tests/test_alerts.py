from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.alerts.service import AlertService
from amazon_geo_rank_monitor.notifications.email import MemoryEmailSender
from amazon_geo_rank_monitor.repositories.alert_repository import AlertRepository
from amazon_geo_rank_monitor.repositories.models import Base


OWNER_ID = "owner-1"
MONITOR_ID = "monitor-1"
ASIN = "B000TEST01"
GEO_ID = "geo-1"


class FakeMonitorRepository:
    def get(self, monitor_id: str, *, owner_id: str):
        if monitor_id != MONITOR_ID or owner_id != OWNER_ID:
            return None
        return {
            "id": MONITOR_ID,
            "owner_id": OWNER_ID,
            "asins": [ASIN],
            "geo_profile_ids": [GEO_ID],
        }


class FakeRankRepository:
    def __init__(self, runs: dict[str, dict]) -> None:
        self.runs = runs

    def get_run(self, run_id: str, *, owner_id: str):
        if owner_id != OWNER_ID or run_id not in self.runs:
            raise KeyError(run_id)
        return self.runs[run_id]


class FakeJobRepository:
    def __init__(self, jobs: list[dict]) -> None:
        self.jobs = jobs

    def list_for_monitor(self, *, owner_id: str, monitor_target_id: str, limit: int):
        assert owner_id == OWNER_ID
        assert monitor_target_id == MONITOR_ID
        return self.jobs[:limit]


def aggregate_run(run_id: str, rank: int, *, found_weight: float = 1.0) -> dict:
    return {
        "id": run_id,
        "owner_id": OWNER_ID,
        "status": "succeeded",
        "snapshots": [
            {
                "asin": ASIN,
                "weighted_rank": Decimal(rank),
                "found_weight": Decimal(str(found_weight)),
                "missing_weight": Decimal(str(1 - found_weight)),
                "confidence": Decimal("1"),
            }
        ],
        "observations": [],
    }


def geo_run(run_id: str, *, found: bool, effective_rank: int) -> dict:
    return {
        "id": run_id,
        "owner_id": OWNER_ID,
        "status": "succeeded",
        "snapshots": [
            {
                "asin": ASIN,
                "weighted_rank": Decimal(effective_rank),
                "found_weight": Decimal("1" if found else "0"),
                "missing_weight": Decimal("0" if found else "1"),
                "confidence": Decimal("1"),
            }
        ],
        "observations": [
            {
                "asin": ASIN,
                "geo_profile_id": GEO_ID,
                "provider": "fake",
                "verification_level": "managed",
                "status": "ok",
                "found": found,
                "organic_rank": effective_rank if found else None,
                "absolute_rank": effective_rank if found else None,
                "sponsored_rank": None,
                "effective_rank": effective_rank,
                "page": 1 if found else None,
            }
        ],
    }


def build_service(
    *,
    runs: dict[str, dict],
    jobs: list[dict],
    handler=None,
    allowed_hosts: list[str] | None = None,
):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    mailer = MemoryEmailSender()
    http = (
        httpx.Client(transport=httpx.MockTransport(handler))
        if handler is not None
        else httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204)))
    )
    service = AlertService(
        repository=AlertRepository(engine),
        rank_repository=FakeRankRepository(runs),
        job_repository=FakeJobRepository(jobs),
        monitor_repository=FakeMonitorRepository(),
        email_sender=mailer,
        encryption_key="alert-test-key",
        webhook_allowed_hosts=allowed_hosts,
        http_client=http,
    )
    return service, mailer


def completed_jobs(current: str, previous: str | None = None) -> list[dict]:
    rows = [
        {
            "run_id": current,
            "status": "succeeded",
            "monitor_target_id": MONITOR_ID,
        }
    ]
    if previous:
        rows.append(
            {
                "run_id": previous,
                "status": "succeeded",
                "monitor_target_id": MONITOR_ID,
            }
        )
    return rows


def test_rank_drop_emits_email_and_cooldown_suppresses_duplicate() -> None:
    runs = {
        "run-prev": aggregate_run("run-prev", 10),
        "run-current": aggregate_run("run-current", 25),
    }
    service, mailer = build_service(
        runs=runs,
        jobs=completed_jobs("run-current", "run-prev"),
    )
    rule = service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Rank dropped by 10+",
        rule_type="rank_drop",
        threshold=Decimal("10"),
        asin=ASIN,
        geo_profile_id=None,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=60,
    )

    assert rule["channels"]["email_count"] == 1
    assert "channels_encrypted" not in rule
    emitted = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="run-current",
    )
    assert len(emitted) == 1
    assert emitted[0]["previous_value"] == Decimal("10")
    assert emitted[0]["current_value"] == Decimal("25")
    assert len(mailer.messages) == 1

    again = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="run-current",
    )
    assert again == []
    assert len(mailer.messages) == 1

    events = service.list_events(owner_id=OWNER_ID)
    assert len(events) == 1
    assert events[0]["deliveries"][0]["status"] == "sent"


@pytest.mark.parametrize(
    ("rule_type", "previous", "current"),
    [
        ("enters_top_n", 15, 8),
        ("exits_top_n", 8, 15),
        ("rank_improve", 30, 12),
    ],
)
def test_threshold_crossing_rules(rule_type: str, previous: int, current: int) -> None:
    service, _ = build_service(
        runs={
            "previous": aggregate_run("previous", previous),
            "current": aggregate_run("current", current),
        },
        jobs=completed_jobs("current", "previous"),
    )
    threshold = 10 if "top_n" in rule_type else 15
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name=rule_type,
        rule_type=rule_type,
        threshold=Decimal(threshold),
        asin=ASIN,
        geo_profile_id=None,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=0,
    )
    assert len(
        service.evaluate_run(
            owner_id=OWNER_ID,
            monitor_target_id=MONITOR_ID,
            run_id="current",
        )
    ) == 1


def test_geo_not_found_and_geo_rank_above() -> None:
    service, _ = build_service(
        runs={"current": geo_run("current", found=False, effective_rank=101)},
        jobs=completed_jobs("current"),
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Geo missing",
        rule_type="geo_not_found",
        threshold=None,
        asin=ASIN,
        geo_profile_id=GEO_ID,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=0,
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Geo rank above 50",
        rule_type="geo_rank_above",
        threshold=Decimal("50"),
        asin=ASIN,
        geo_profile_id=GEO_ID,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=0,
    )
    events = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="current",
    )
    assert {item["event_type"] for item in events} == {
        "geo_not_found",
        "geo_rank_above",
    }


def test_not_found_aggregate_alert() -> None:
    service, _ = build_service(
        runs={"current": aggregate_run("current", 101, found_weight=0)},
        jobs=completed_jobs("current"),
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Missing everywhere",
        rule_type="not_found",
        threshold=None,
        asin=ASIN,
        geo_profile_id=None,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=0,
    )
    events = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="current",
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "not_found"


def test_private_webhook_targets_are_rejected_and_urls_are_not_exposed() -> None:
    service, _ = build_service(
        runs={},
        jobs=[],
    )
    with pytest.raises(ValueError, match="private webhook"):
        service.create_rule(
            owner_id=OWNER_ID,
            monitor_target_id=MONITOR_ID,
            name="Bad webhook",
            rule_type="not_found",
            threshold=None,
            asin=ASIN,
            geo_profile_id=None,
            channels={"webhook_url": "https://127.0.0.1/hook"},
            cooldown_minutes=60,
        )

    rule = service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Slack",
        rule_type="not_found",
        threshold=None,
        asin=ASIN,
        geo_profile_id=None,
        channels={"slack_webhook_url": "https://hooks.slack.com/services/T/B/X"},
        cooldown_minutes=60,
    )
    assert rule["channels"]["has_slack"] is True
    assert "slack_webhook_url" not in rule["channels"]


def test_webhook_delivery_records_masked_destination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    service, _ = build_service(
        runs={"current": aggregate_run("current", 101, found_weight=0)},
        jobs=completed_jobs("current"),
        handler=handler,
        allowed_hosts=["alerts.example.com"],
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Webhook",
        rule_type="not_found",
        threshold=None,
        asin=ASIN,
        geo_profile_id=None,
        channels={"webhook_url": "https://alerts.example.com/secret/token"},
        cooldown_minutes=0,
    )
    service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="current",
    )
    assert len(requests) == 1
    assert requests[0].headers["X-AGRM-Event-ID"]
    delivery = service.list_events(owner_id=OWNER_ID)[0]["deliveries"][0]
    assert delivery["destination"] == "https://alerts.example.com/***"
    assert "secret" not in delivery["destination"]
