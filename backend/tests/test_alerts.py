from datetime import UTC, datetime
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
COMPETITOR_ASIN = "B000COMP01"
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


class FakeCompetitiveRepository:
    def __init__(self, points: dict[str, list[dict]] | None = None) -> None:
        self.points = points or {}

    def run_points(self, *, owner_id: str, run_id: str) -> list[dict]:
        assert owner_id == OWNER_ID
        return self.points.get(run_id, [])


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


def verification_run(
    run_id: str,
    *,
    skipped_reason: str | None = None,
    error: str | None = None,
    attempted: bool = False,
    succeeded: bool = False,
) -> dict:
    run = aggregate_run(run_id, 10)
    run["verification_metadata"] = {
        "manual_force_requested": True,
        "auto_strict_max_upstream_probes_per_run": 1,
        "strict_upstream_attempt_count": 1 if attempted else 0,
        "events": [
            {
                "geo_profile_id": GEO_ID,
                "requested": True,
                "attempted": attempted,
                "succeeded": succeeded,
                "cache_hit": False,
                "triggers": ["manual_force"],
                "skipped_reason": skipped_reason,
                "error": error,
            }
        ],
    }
    return run


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
    competitive_points: dict[str, list[dict]] | None = None,
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
        competitive_repository=FakeCompetitiveRepository(competitive_points),
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


def test_cooldown_suppresses_distinct_run_ids() -> None:
    runs = {
        "run-prev": aggregate_run("run-prev", 10),
        "run-current": aggregate_run("run-current", 25),
        "run-next": aggregate_run("run-next", 40),
    }
    service, mailer = build_service(
        runs=runs,
        jobs=completed_jobs("run-current", "run-prev"),
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Rank dropped repeatedly",
        rule_type="rank_drop",
        threshold=Decimal("10"),
        asin=ASIN,
        geo_profile_id=None,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=60,
    )

    first = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="run-current",
    )
    assert len(first) == 1

    service._jobs.jobs = completed_jobs("run-next", "run-current")
    second = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="run-next",
    )
    assert second == []
    assert len(mailer.messages) == 1


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


@pytest.mark.parametrize(
    ("rule_type", "skipped_reason"),
    [
        ("strict_insufficient_credits", "insufficient_credits"),
        ("strict_probe_budget_exhausted", "probe_budget_exhausted"),
        ("strict_provider_unavailable", "strict_provider_unavailable"),
        ("strict_runtime_disabled", "runtime_kill_switch_disabled"),
    ],
)
def test_verification_skip_rules_emit_probe_level_alerts(
    rule_type: str,
    skipped_reason: str,
) -> None:
    service, mailer = build_service(
        runs={
            "current": verification_run(
                "current",
                skipped_reason=skipped_reason,
            )
        },
        jobs=completed_jobs("current"),
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name=rule_type,
        rule_type=rule_type,
        threshold=None,
        asin=None,
        geo_profile_id=GEO_ID,
        channels={"emails": ["alerts@example.com"]},
        cooldown_minutes=0,
    )

    events = service.evaluate_run(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        run_id="current",
    )

    assert len(events) == 1
    assert events[0]["event_type"] == rule_type
    assert events[0]["asin"] == "VERIFICATION"
    assert events[0]["geo_profile_id"] == GEO_ID
    assert events[0]["details"]["scope"] == "verification"
    assert events[0]["details"]["skipped_reason"] == skipped_reason
    assert events[0]["details"]["manual_force_requested"] is True
    assert len(mailer.messages) == 1
    assert "Scope: strict verification" in mailer.messages[0].text
    assert f"Reason: {skipped_reason}" in mailer.messages[0]["text"]


def test_strict_verification_failure_alert_includes_provider_error() -> None:
    service, mailer = build_service(
        runs={
            "current": verification_run(
                "current",
                attempted=True,
                error="browser navigation failed",
            )
        },
        jobs=completed_jobs("current"),
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Strict browser failed",
        rule_type="strict_verification_failed",
        threshold=None,
        asin=None,
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
    assert events[0]["event_type"] == "strict_verification_failed"
    assert events[0]["details"]["error"] == "browser navigation failed"
    assert "Reason: browser navigation failed" in mailer.messages[0]["text"]


def test_verification_alert_rules_reject_asin_scope() -> None:
    service, _ = build_service(runs={}, jobs=[])
    with pytest.raises(
        ValueError,
        match="verification alert rules do not use ASIN scope",
    ):
        service.create_rule(
            owner_id=OWNER_ID,
            monitor_target_id=MONITOR_ID,
            name="Invalid verification scope",
            rule_type="strict_verification_failed",
            threshold=None,
            asin=ASIN,
            geo_profile_id=None,
            channels={"emails": ["alerts@example.com"]},
            cooldown_minutes=0,
        )


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



def competitive_point(
    run_id: str,
    asin: str,
    organic_position: int | None,
    *,
    geo_profile_id: str,
) -> dict:
    return {
        "run_id": run_id,
        "geo_profile_id": geo_profile_id,
        "asin": asin,
        "title": asin + " title",
        "organic_position": organic_position,
        "sponsored_position": None,
        "absolute_position": organic_position,
        "probe_source": "upstream",
        "cache_age_seconds": None,
        "observed_at": datetime.now(UTC),
    }


def test_competitor_enters_top_n_emits_transition_alert() -> None:
    service, _ = build_service(
        runs={
            "previous": aggregate_run("previous", 12),
            "current": aggregate_run("current", 11),
        },
        jobs=completed_jobs("current", "previous"),
        competitive_points={
            "previous": [
                competitive_point("previous", ASIN, 5, geo_profile_id="geo-1"),
                competitive_point(
                    "previous",
                    COMPETITOR_ASIN,
                    18,
                    geo_profile_id="geo-1",
                ),
            ],
            "current": [
                competitive_point("current", ASIN, 6, geo_profile_id="geo-1"),
                competitive_point(
                    "current",
                    COMPETITOR_ASIN,
                    8,
                    geo_profile_id="geo-1",
                ),
            ],
        },
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Competitor entered Top 10",
        rule_type="competitor_enters_top_n",
        threshold=Decimal("10"),
        asin=COMPETITOR_ASIN,
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
    assert events[0]["event_type"] == "competitor_enters_top_n"
    assert events[0]["previous_value"] == Decimal("18")
    assert events[0]["current_value"] == Decimal("8")
    assert events[0]["details"]["scope"] == "competitive"


def test_competitor_sov_gain_compares_adjacent_runs() -> None:
    service, _ = build_service(
        runs={
            "previous": aggregate_run("previous", 10),
            "current": aggregate_run("current", 10),
        },
        jobs=completed_jobs("current", "previous"),
        competitive_points={
            "previous": [
                competitive_point("previous", ASIN, 4, geo_profile_id="g1"),
                competitive_point("previous", ASIN, 5, geo_profile_id="g2"),
                competitive_point(
                    "previous",
                    COMPETITOR_ASIN,
                    9,
                    geo_profile_id="g1",
                ),
                competitive_point("previous", "B000OTHER1", 12, geo_profile_id="g2"),
            ],
            "current": [
                competitive_point("current", ASIN, 5, geo_profile_id="g1"),
                competitive_point(
                    "current",
                    COMPETITOR_ASIN,
                    6,
                    geo_profile_id="g1",
                ),
                competitive_point(
                    "current",
                    COMPETITOR_ASIN,
                    7,
                    geo_profile_id="g2",
                ),
                competitive_point(
                    "current",
                    COMPETITOR_ASIN,
                    8,
                    geo_profile_id="g3",
                ),
            ],
        },
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Competitor SOV jump",
        rule_type="competitor_sov_gain",
        threshold=Decimal("40"),
        asin=COMPETITOR_ASIN,
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
    assert events[0]["previous_value"] == Decimal("25.0")
    assert events[0]["current_value"] == Decimal("75.0")
    assert events[0]["details"]["sov_change_pct_points"] == 50.0


def test_competitor_overtakes_best_tracked_product_once() -> None:
    service, _ = build_service(
        runs={
            "previous": aggregate_run("previous", 10),
            "current": aggregate_run("current", 10),
        },
        jobs=completed_jobs("current", "previous"),
        competitive_points={
            "previous": [
                competitive_point("previous", ASIN, 8, geo_profile_id="g1"),
                competitive_point(
                    "previous",
                    COMPETITOR_ASIN,
                    14,
                    geo_profile_id="g1",
                ),
            ],
            "current": [
                competitive_point("current", ASIN, 9, geo_profile_id="g1"),
                competitive_point(
                    "current",
                    COMPETITOR_ASIN,
                    5,
                    geo_profile_id="g1",
                ),
            ],
        },
    )
    service.create_rule(
        owner_id=OWNER_ID,
        monitor_target_id=MONITOR_ID,
        name="Competitor overtook us",
        rule_type="competitor_overtakes_tracked",
        threshold=None,
        asin=COMPETITOR_ASIN,
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
    assert events[0]["current_value"] == Decimal("5.0")
    assert events[0]["details"]["current_best_tracked_average_rank"] == 9


def test_competitor_rule_requires_untracked_valid_asin() -> None:
    service, _ = build_service(
        runs={"current": aggregate_run("current", 10)},
        jobs=completed_jobs("current"),
    )
    with pytest.raises(ValueError, match="must not be a tracked ASIN"):
        service.create_rule(
            owner_id=OWNER_ID,
            monitor_target_id=MONITOR_ID,
            name="Invalid competitor",
            rule_type="competitor_sov_gain",
            threshold=Decimal("10"),
            asin=ASIN,
            geo_profile_id=None,
            channels={"emails": ["alerts@example.com"]},
            cooldown_minutes=0,
        )
