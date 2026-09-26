from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
from collections import defaultdict
from decimal import Decimal
from statistics import fmean
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("amazon_geo_rank_monitor.alerts")

RULE_TYPES = frozenset(
    {
        "rank_drop",
        "rank_improve",
        "enters_top_n",
        "exits_top_n",
        "not_found",
        "geo_not_found",
        "geo_rank_above",
        "competitor_enters_top_n",
        "competitor_exits_top_n",
        "competitor_sov_gain",
        "competitor_sov_loss",
        "competitor_overtakes_tracked",
    }
)
VERIFICATION_TYPES = frozenset(
    {
        "strict_verification_failed",
        "strict_insufficient_credits",
        "strict_probe_budget_exhausted",
        "strict_provider_unavailable",
        "strict_runtime_disabled",
    }
)
COMPETITIVE_TYPES = frozenset(
    {
        "competitor_enters_top_n",
        "competitor_exits_top_n",
        "competitor_sov_gain",
        "competitor_sov_loss",
        "competitor_overtakes_tracked",
    }
)
THRESHOLD_TYPES = frozenset(
    {
        "rank_drop",
        "rank_improve",
        "enters_top_n",
        "exits_top_n",
        "geo_rank_above",
        "competitor_enters_top_n",
        "competitor_exits_top_n",
        "competitor_sov_gain",
        "competitor_sov_loss",
    }
)
GEO_TYPES = frozenset({"geo_not_found", "geo_rank_above"})
GEO_SCOPE_TYPES = GEO_TYPES | VERIFICATION_TYPES


class AlertService:
    def __init__(
        self,
        *,
        repository,
        rank_repository,
        job_repository,
        monitor_repository,
        competitive_repository,
        email_sender,
        encryption_key: str,
        webhook_allowed_hosts: list[str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not encryption_key:
            raise ValueError("alert encryption key is required")
        digest = hashlib.sha256(encryption_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._repository = repository
        self._ranks = rank_repository
        self._jobs = job_repository
        self._monitors = monitor_repository
        self._competitive = competitive_repository
        self._email = email_sender
        self._http = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
        self._allowed_hosts = {
            item.strip().lower()
            for item in (webhook_allowed_hosts or [])
            if item.strip()
        }

    def create_rule(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        name: str,
        rule_type: str,
        threshold: Decimal | None,
        asin: str | None,
        geo_profile_id: str | None,
        channels: dict,
        cooldown_minutes: int,
        enabled: bool = True,
    ) -> dict:
        monitor = self._monitors.get(monitor_target_id, owner_id=owner_id)
        if monitor is None:
            raise KeyError("monitor not found")
        normalized = self._validate_rule(
            name=name,
            rule_type=rule_type,
            threshold=threshold,
            asin=asin,
            geo_profile_id=geo_profile_id,
            channels=channels,
            cooldown_minutes=cooldown_minutes,
            monitor=monitor,
        )
        row = self._repository.create_rule(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            name=normalized["name"],
            rule_type=normalized["rule_type"],
            threshold=normalized["threshold"],
            asin=normalized["asin"],
            geo_profile_id=normalized["geo_profile_id"],
            channels_encrypted=self._encrypt_channels(normalized["channels"]),
            cooldown_minutes=normalized["cooldown_minutes"],
            enabled=enabled,
        )
        return self._public_rule(row)

    def update_rule(
        self,
        *,
        owner_id: str,
        rule_id: str,
        changes: dict,
    ) -> dict:
        existing = self._repository.get_rule(owner_id=owner_id, rule_id=rule_id)
        monitor_id = changes.get(
            "monitor_target_id",
            existing["monitor_target_id"],
        )
        if not monitor_id:
            raise ValueError("monitor_target_id is required")
        monitor = self._monitors.get(monitor_id, owner_id=owner_id)
        if monitor is None:
            raise KeyError("monitor not found")
        channels = (
            changes["channels"]
            if "channels" in changes and changes["channels"] is not None
            else self._decrypt_channels(existing["channels_encrypted"])
        )
        normalized = self._validate_rule(
            name=changes.get("name", existing["name"]),
            rule_type=changes.get("rule_type", existing["rule_type"]),
            threshold=changes.get("threshold", existing["threshold"]),
            asin=changes.get("asin", existing["asin"]),
            geo_profile_id=changes.get(
                "geo_profile_id",
                existing["geo_profile_id"],
            ),
            channels=channels,
            cooldown_minutes=changes.get(
                "cooldown_minutes",
                existing["cooldown_minutes"],
            ),
            monitor=monitor,
        )
        payload = {
            "monitor_target_id": monitor_id,
            "name": normalized["name"],
            "rule_type": normalized["rule_type"],
            "threshold": normalized["threshold"],
            "asin": normalized["asin"],
            "geo_profile_id": normalized["geo_profile_id"],
            "cooldown_minutes": normalized["cooldown_minutes"],
        }
        if "channels" in changes and changes["channels"] is not None:
            payload["channels_encrypted"] = self._encrypt_channels(
                normalized["channels"]
            )
        if "enabled" in changes and changes["enabled"] is not None:
            payload["enabled"] = bool(changes["enabled"])
        row = self._repository.update_rule(
            owner_id=owner_id,
            rule_id=rule_id,
            changes=payload,
        )
        return self._public_rule(row)

    def list_rules(self, *, owner_id: str) -> list[dict]:
        return [
            self._public_rule(row)
            for row in self._repository.list_rules(owner_id=owner_id)
        ]

    def get_rule(self, *, owner_id: str, rule_id: str) -> dict:
        return self._public_rule(
            self._repository.get_rule(owner_id=owner_id, rule_id=rule_id)
        )

    def delete_rule(self, *, owner_id: str, rule_id: str) -> None:
        self._repository.delete_rule(owner_id=owner_id, rule_id=rule_id)

    def list_events(self, *, owner_id: str, limit: int = 100) -> list[dict]:
        return self._repository.list_events(owner_id=owner_id, limit=limit)

    def evaluate_run(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        run_id: str,
    ) -> list[dict]:
        rules = self._repository.list_enabled_for_monitor(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
        )
        if not rules:
            return []

        current = self._ranks.get_run(run_id, owner_id=owner_id)
        previous = self._previous_run(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            current_run_id=run_id,
        )
        emitted: list[dict] = []
        for rule in rules:
            try:
                if rule["rule_type"] in COMPETITIVE_TYPES:
                    candidates = self._evaluate_competitive_rule(
                        rule=rule,
                        monitor=self._monitors.get(
                            monitor_target_id,
                            owner_id=owner_id,
                        ),
                        current_run_id=run_id,
                        previous_run_id=previous["id"] if previous else None,
                    )
                else:
                    candidates = self._evaluate_rule(
                        rule=rule,
                        current=current,
                        previous=previous,
                    )
                for candidate in candidates:
                    event = self._emit_candidate(
                        rule=rule,
                        monitor_target_id=monitor_target_id,
                        run_id=run_id,
                        candidate=candidate,
                    )
                    if event is not None:
                        emitted.append(event)
            except Exception:
                logger.exception(
                    "alert_rule_evaluation_failed rule_id=%s run_id=%s",
                    rule["id"],
                    run_id,
                )
        return emitted

    def _previous_run(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        current_run_id: str,
    ) -> dict | None:
        jobs = self._jobs.list_for_monitor(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            limit=20,
        )
        for job in jobs:
            if (
                job["run_id"]
                and job["run_id"] != current_run_id
                and job["status"] in {"succeeded", "partially_succeeded"}
            ):
                try:
                    return self._ranks.get_run(
                        job["run_id"],
                        owner_id=owner_id,
                    )
                except KeyError:
                    continue
        return None

    def _evaluate_rule(
        self,
        *,
        rule: dict,
        current: dict,
        previous: dict | None,
    ) -> list[dict]:
        rule_type = rule["rule_type"]
        asin_filter = rule["asin"]
        geo_filter = rule["geo_profile_id"]
        threshold = (
            Decimal(str(rule["threshold"]))
            if rule["threshold"] is not None
            else None
        )

        if rule_type in VERIFICATION_TYPES:
            return self._evaluate_verification(
                rule_type=rule_type,
                current=current,
                geo_filter=geo_filter,
            )

        if rule_type in GEO_TYPES:
            return self._evaluate_geo(
                rule_type=rule_type,
                current=current,
                threshold=threshold,
                asin_filter=asin_filter,
                geo_filter=geo_filter,
            )

        current_map = {
            row["asin"]: Decimal(str(row["weighted_rank"]))
            for row in current["snapshots"]
        }
        previous_map = (
            {
                row["asin"]: Decimal(str(row["weighted_rank"]))
                for row in previous["snapshots"]
            }
            if previous
            else {}
        )
        candidates = []
        for asin, current_rank in current_map.items():
            if asin_filter and asin != asin_filter:
                continue
            previous_rank = previous_map.get(asin)
            if rule_type == "not_found":
                snapshot = next(
                    row for row in current["snapshots"] if row["asin"] == asin
                )
                if Decimal(str(snapshot["found_weight"])) == 0:
                    candidates.append(
                        self._candidate(
                            asin=asin,
                            event_type=rule_type,
                            previous_value=previous_rank,
                            current_value=current_rank,
                            details={"scope": "aggregate"},
                        )
                    )
                continue
            if previous_rank is None or threshold is None:
                continue
            triggered = False
            if rule_type == "rank_drop":
                triggered = current_rank - previous_rank >= threshold
            elif rule_type == "rank_improve":
                triggered = previous_rank - current_rank >= threshold
            elif rule_type == "enters_top_n":
                triggered = current_rank <= threshold < previous_rank
            elif rule_type == "exits_top_n":
                triggered = previous_rank <= threshold < current_rank
            if triggered:
                candidates.append(
                    self._candidate(
                        asin=asin,
                        event_type=rule_type,
                        previous_value=previous_rank,
                        current_value=current_rank,
                        details={"scope": "aggregate"},
                    )
                )
        return candidates

    def _evaluate_verification(
        self,
        *,
        rule_type: str,
        current: dict,
        geo_filter: str | None,
    ) -> list[dict]:
        metadata = current.get("verification_metadata") or {}
        events = metadata.get("events") or []
        skip_reason_by_type = {
            "strict_insufficient_credits": "insufficient_credits",
            "strict_probe_budget_exhausted": "probe_budget_exhausted",
            "strict_provider_unavailable": "strict_provider_unavailable",
            "strict_runtime_disabled": "runtime_kill_switch_disabled",
        }
        candidates: list[dict] = []
        for event in events:
            geo_profile_id = event.get("geo_profile_id")
            if geo_filter and geo_profile_id != geo_filter:
                continue

            if rule_type == "strict_verification_failed":
                triggered = bool(
                    event.get("error")
                    or (
                        event.get("attempted")
                        and not event.get("succeeded")
                        and not event.get("skipped_reason")
                    )
                )
            else:
                triggered = (
                    event.get("skipped_reason")
                    == skip_reason_by_type.get(rule_type)
                )
            if not triggered:
                continue

            candidates.append(
                self._candidate(
                    asin="VERIFICATION",
                    event_type=rule_type,
                    previous_value=None,
                    current_value=None,
                    geo_profile_id=geo_profile_id,
                    details={
                        "scope": "verification",
                        "triggers": list(event.get("triggers") or []),
                        "attempted": bool(event.get("attempted")),
                        "succeeded": bool(event.get("succeeded")),
                        "cache_hit": bool(event.get("cache_hit")),
                        "skipped_reason": event.get("skipped_reason"),
                        "error": event.get("error"),
                        "manual_force_requested": bool(
                            metadata.get("manual_force_requested")
                        ),
                        "strict_upstream_attempt_count": metadata.get(
                            "strict_upstream_attempt_count"
                        ),
                        "strict_probe_budget": metadata.get(
                            "auto_strict_max_upstream_probes_per_run"
                        ),
                    },
                )
            )
        return candidates

    def _evaluate_competitive_rule(
        self,
        *,
        rule: dict,
        monitor: dict | None,
        current_run_id: str,
        previous_run_id: str | None,
    ) -> list[dict]:
        if monitor is None or previous_run_id is None:
            return []
        asin = rule["asin"]
        if not asin:
            return []

        current_points = self._competitive.run_points(
            owner_id=rule["owner_id"],
            run_id=current_run_id,
        )
        previous_points = self._competitive.run_points(
            owner_id=rule["owner_id"],
            run_id=previous_run_id,
        )
        current = self._competitive_metrics(
            current_points,
            tracked=set(monitor["asins"]),
        )
        previous = self._competitive_metrics(
            previous_points,
            tracked=set(monitor["asins"]),
        )
        current_target = current["asins"].get(asin, self._empty_competitive_metric())
        previous_target = previous["asins"].get(
            asin,
            self._empty_competitive_metric(),
        )
        threshold = (
            Decimal(str(rule["threshold"]))
            if rule["threshold"] is not None
            else None
        )
        rule_type = rule["rule_type"]
        triggered = False
        previous_value = None
        current_value = None
        details = {
            "scope": "competitive",
            "title": current_target.get("title") or previous_target.get("title"),
            "previous_sov_pct": previous_target["sov_pct"],
            "current_sov_pct": current_target["sov_pct"],
            "previous_best_rank": previous_target["best_rank"],
            "current_best_rank": current_target["best_rank"],
            "previous_average_rank": previous_target["average_rank"],
            "current_average_rank": current_target["average_rank"],
        }

        if rule_type in {"competitor_enters_top_n", "competitor_exits_top_n"}:
            if threshold is None:
                return []
            previous_rank = previous_target["best_rank"]
            current_rank = current_target["best_rank"]
            previous_in = previous_rank is not None and previous_rank <= threshold
            current_in = current_rank is not None and current_rank <= threshold
            triggered = (
                current_in and not previous_in
                if rule_type == "competitor_enters_top_n"
                else previous_in and not current_in
            )
            previous_value = previous_rank
            current_value = current_rank
            details["top_n"] = int(threshold)
        elif rule_type in {"competitor_sov_gain", "competitor_sov_loss"}:
            if threshold is None:
                return []
            previous_sov = Decimal(str(previous_target["sov_pct"]))
            current_sov = Decimal(str(current_target["sov_pct"]))
            delta = current_sov - previous_sov
            triggered = (
                delta >= threshold
                if rule_type == "competitor_sov_gain"
                else -delta >= threshold
            )
            previous_value = previous_sov
            current_value = current_sov
            details["sov_change_pct_points"] = float(delta)
        elif rule_type == "competitor_overtakes_tracked":
            previous_rank = previous_target["average_rank"]
            current_rank = current_target["average_rank"]
            previous_tracked = previous["best_tracked_average_rank"]
            current_tracked = current["best_tracked_average_rank"]
            if (
                current_rank is not None
                and current_tracked is not None
                and previous_tracked is not None
            ):
                previous_ahead = (
                    previous_rank is not None
                    and previous_rank < previous_tracked
                )
                current_ahead = current_rank < current_tracked
                triggered = current_ahead and not previous_ahead
            previous_value = previous_rank
            current_value = current_rank
            details["previous_best_tracked_average_rank"] = previous_tracked
            details["current_best_tracked_average_rank"] = current_tracked

        if not triggered:
            return []
        return [
            self._candidate(
                asin=asin,
                event_type=rule_type,
                previous_value=(
                    Decimal(str(previous_value))
                    if previous_value is not None
                    else None
                ),
                current_value=(
                    Decimal(str(current_value))
                    if current_value is not None
                    else None
                ),
                details=details,
            )
        ]

    @classmethod
    def _competitive_metrics(
        cls,
        points: list[dict],
        *,
        tracked: set[str],
    ) -> dict:
        organic_total = sum(
            1 for row in points if row["organic_position"] is not None
        )
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in points:
            grouped[row["asin"]].append(row)

        asins: dict[str, dict] = {}
        for asin, rows in grouped.items():
            organic = [
                int(row["organic_position"])
                for row in rows
                if row["organic_position"] is not None
            ]
            latest = max(
                rows,
                key=lambda row: row["observed_at"],
            )
            asins[asin] = {
                "title": latest.get("title"),
                "best_rank": min(organic) if organic else None,
                "average_rank": round(fmean(organic), 2) if organic else None,
                "sov_pct": (
                    round((len(organic) / organic_total) * 100, 2)
                    if organic_total
                    else 0.0
                ),
            }
        tracked_averages = [
            metric["average_rank"]
            for asin, metric in asins.items()
            if asin in tracked and metric["average_rank"] is not None
        ]
        return {
            "asins": asins,
            "best_tracked_average_rank": (
                min(tracked_averages) if tracked_averages else None
            ),
        }

    @staticmethod
    def _empty_competitive_metric() -> dict:
        return {
            "title": None,
            "best_rank": None,
            "average_rank": None,
            "sov_pct": 0.0,
        }

    def _evaluate_geo(
        self,
        *,
        rule_type: str,
        current: dict,
        threshold: Decimal | None,
        asin_filter: str | None,
        geo_filter: str | None,
    ) -> list[dict]:
        candidates = []
        for row in current["observations"]:
            if asin_filter and row["asin"] != asin_filter:
                continue
            if geo_filter and row["geo_profile_id"] != geo_filter:
                continue
            if rule_type == "geo_not_found":
                triggered = not row["found"]
            else:
                triggered = (
                    threshold is not None
                    and Decimal(str(row["effective_rank"])) > threshold
                )
            if triggered:
                candidates.append(
                    self._candidate(
                        asin=row["asin"],
                        event_type=rule_type,
                        previous_value=None,
                        current_value=Decimal(str(row["effective_rank"])),
                        geo_profile_id=row["geo_profile_id"],
                        details={
                            "scope": "geo",
                            "organic_rank": row["organic_rank"],
                            "absolute_rank": row["absolute_rank"],
                            "sponsored_rank": row["sponsored_rank"],
                            "found": row["found"],
                        },
                    )
                )
        return candidates

    @staticmethod
    def _candidate(
        *,
        asin: str,
        event_type: str,
        previous_value: Decimal | None,
        current_value: Decimal | None,
        details: dict,
        geo_profile_id: str | None = None,
    ) -> dict:
        return {
            "asin": asin,
            "event_type": event_type,
            "previous_value": previous_value,
            "current_value": current_value,
            "geo_profile_id": geo_profile_id,
            "details": details,
        }

    def _emit_candidate(
        self,
        *,
        rule: dict,
        monitor_target_id: str,
        run_id: str,
        candidate: dict,
    ) -> dict | None:
        raw = "|".join(
            [
                rule["id"],
                run_id,
                candidate["asin"],
                candidate["geo_profile_id"] or "",
                candidate["event_type"],
            ]
        )
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        event = self._repository.create_event_if_not_cooling(
            owner_id=rule["owner_id"],
            rule_id=rule["id"],
            monitor_target_id=monitor_target_id,
            run_id=run_id,
            asin=candidate["asin"],
            geo_profile_id=candidate["geo_profile_id"],
            event_type=candidate["event_type"],
            fingerprint=fingerprint,
            previous_value=candidate["previous_value"],
            current_value=candidate["current_value"],
            details=candidate["details"],
            cooldown_minutes=rule["cooldown_minutes"],
        )
        if event is None:
            return None
        channels = self._decrypt_channels(rule["channels_encrypted"])
        self._deliver(event=event, rule=rule, channels=channels)
        return event

    def _deliver(self, *, event: dict, rule: dict, channels: dict) -> None:
        subject = f"[Geo Rank Alert] {rule['name']}: {event['asin']}"
        summary = self._summary(event=event, rule=rule)
        for address in channels.get("emails", []):
            try:
                self._email.send(to=address, subject=subject, text=summary)
                self._record_delivery(
                    event_id=event["id"],
                    channel_type="email",
                    destination=address,
                    status="sent",
                )
            except Exception as exc:
                self._record_delivery(
                    event_id=event["id"],
                    channel_type="email",
                    destination=address,
                    status="failed",
                    error=str(exc),
                )

        slack_url = channels.get("slack_webhook_url")
        if slack_url:
            self._post_webhook(
                event=event,
                url=slack_url,
                channel_type="slack",
                payload={"text": summary},
            )

        webhook_url = channels.get("webhook_url")
        if webhook_url:
            self._post_webhook(
                event=event,
                url=webhook_url,
                channel_type="webhook",
                payload={
                    "event": "rank_alert.triggered",
                    "event_id": event["id"],
                    "rule_id": event["rule_id"],
                    "monitor_target_id": event["monitor_target_id"],
                    "run_id": event["run_id"],
                    "asin": event["asin"],
                    "geo_profile_id": event["geo_profile_id"],
                    "event_type": event["event_type"],
                    "previous_value": (
                        str(event["previous_value"])
                        if event["previous_value"] is not None
                        else None
                    ),
                    "current_value": (
                        str(event["current_value"])
                        if event["current_value"] is not None
                        else None
                    ),
                    "details": event["details"],
                    "created_at": event["created_at"].isoformat(),
                },
            )

    def _post_webhook(
        self,
        *,
        event: dict,
        url: str,
        channel_type: str,
        payload: dict,
    ) -> None:
        try:
            response = self._http.post(
                url,
                json=payload,
                headers={
                    "User-Agent": "amazon-geo-rank-monitor/alerts",
                    "X-AGRM-Event-ID": event["id"],
                },
            )
            response.raise_for_status()
            self._record_delivery(
                event_id=event["id"],
                channel_type=channel_type,
                destination=self._mask_url(url),
                status="sent",
            )
        except Exception as exc:
            self._record_delivery(
                event_id=event["id"],
                channel_type=channel_type,
                destination=self._mask_url(url),
                status="failed",
                error=str(exc),
            )

    def _record_delivery(self, **kwargs) -> None:
        try:
            self._repository.record_delivery(**kwargs)
        except Exception:
            logger.exception(
                "alert_delivery_record_failed event_id=%s",
                kwargs.get("event_id"),
            )

    @staticmethod
    def _summary(*, event: dict, rule: dict) -> str:
        previous = (
            str(event["previous_value"])
            if event["previous_value"] is not None
            else "n/a"
        )
        current = (
            str(event["current_value"])
            if event["current_value"] is not None
            else "n/a"
        )
        geo = event["geo_profile_id"] or "aggregate"
        if (event.get("details", {}).get("scope") == "verification":
            reason = (
                event["details"].get("skipped_reason")
                or event["details"].get("error")
                or "strict verification failed"
            )
            return (
                f"Rule: {rule['name']}\n"
                f"Event: {event['event_type']}\n"
                f"Scope: strict verification\n"
                f"Geo: {geo}\n"
                f"Reason: {reason}\n"
                f"Run: {event['run_id']}\n"
            )
        return (
            f"Rule: {rule['name']}\n"
            f"Event: {event['event_type']}\n"
            f"ASIN: {event['asin']}\n"
            f"Geo: {geo}\n"
            f"Previous: {previous}\n"
            f"Current: {current}\n"
            f"Run: {event['run_id']}\n"
        )

    def _validate_rule(
        self,
        *,
        name: str,
        rule_type: str,
        threshold,
        asin: str | None,
        geo_profile_id: str | None,
        channels: dict,
        cooldown_minutes: int,
        monitor: dict,
    ) -> dict:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("alert rule name is required")
        if rule_type not in RULE_TYPES:
            raise ValueError("unsupported alert rule type")
        normalized_threshold = (
            Decimal(str(threshold)) if threshold is not None else None
        )
        if rule_type in THRESHOLD_TYPES:
            if normalized_threshold is None or normalized_threshold <= 0:
                raise ValueError("positive threshold is required for this rule")
        else:
            normalized_threshold = None
        normalized_asin = asin.strip().upper() if asin else None
        if rule_type in VERIFICATION_TYPES:
            if normalized_asin:
                raise ValueError(
                    "verification alert rules do not use ASIN scope"
                )
        elif rule_type in COMPETITIVE_TYPES:
            if not normalized_asin:
                raise ValueError("competitor alert rules require an ASIN")
            if (
                len(normalized_asin) != 10
                or not normalized_asin.isalnum()
            ):
                raise ValueError("competitor ASIN must be 10 alphanumeric characters")
            if normalized_asin in monitor["asins"]:
                raise ValueError("competitor ASIN must not be a tracked ASIN")
        elif normalized_asin and normalized_asin not in monitor["asins"]:
            raise ValueError("alert ASIN is not part of the monitor")
        normalized_geo = geo_profile_id.strip() if geo_profile_id else None
        if normalized_geo and normalized_geo not in monitor["geo_profile_ids"]:
            raise ValueError("alert geo profile is not part of the monitor")
        if rule_type not in GEO_SCOPE_TYPES and normalized_geo:
            raise ValueError(
                "geo_profile_id is only valid for geo or verification alert rules"
            )
        if rule_type in COMPETITIVE_TYPES and normalized_geo:
            raise ValueError("competitive alert rules use monitor-wide geo scope")
        if cooldown_minutes < 0 or cooldown_minutes > 10080:
            raise ValueError("cooldown_minutes must be between 0 and 10080")
        normalized_channels = self._validate_channels(channels)
        return {
            "name": normalized_name,
            "rule_type": rule_type,
            "threshold": normalized_threshold,
            "asin": normalized_asin,
            "geo_profile_id": normalized_geo,
            "channels": normalized_channels,
            "cooldown_minutes": cooldown_minutes,
        }

    def _validate_channels(self, channels: dict) -> dict:
        if not isinstance(channels, dict):
            raise ValueError("channels must be an object")
        emails = []
        for value in channels.get("emails", []) or []:
            email = str(value).strip().lower()
            if "@" not in email or email.startswith("@") or email.endswith("@"):
                raise ValueError("invalid alert email destination")
            emails.append(email)
        emails = list(dict.fromkeys(emails))

        slack = str(channels.get("slack_webhook_url") or "").strip() or None
        webhook = str(channels.get("webhook_url") or "").strip() or None
        if slack:
            self._validate_webhook_url(slack, slack=True)
        if webhook:
            self._validate_webhook_url(webhook, slack=False)
        if not emails and not slack and not webhook:
            raise ValueError("at least one alert notification channel is required")
        return {
            "emails": emails,
            "slack_webhook_url": slack,
            "webhook_url": webhook,
        }

    def _validate_webhook_url(self, url: str, *, slack: bool) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("webhook URLs must use HTTPS")
        host = parsed.hostname.lower()
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("invalid webhook URL")
        if slack and host not in {"hooks.slack.com", "hooks.slack-gov.com"}:
            raise ValueError("Slack webhook must use an official Slack host")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("private webhook targets are not allowed")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("private webhook targets are not allowed")
        if not slack:
            if not self._allowed_hosts:
                raise ValueError(
                    "generic webhooks require ALERT_WEBHOOK_ALLOWED_HOSTS"
                )
            if host not in self._allowed_hosts:
                raise ValueError(
                    "webhook host is not in ALERT_WEBHOOK_ALLOWED_HOSTS"
                )

    def _encrypt_channels(self, channels: dict) -> str:
        raw = json.dumps(channels, separators=(",", ":"), sort_keys=True)
        return self._fernet.encrypt(raw.encode()).decode()

    def _decrypt_channels(self, encrypted: str) -> dict:
        try:
            raw = self._fernet.decrypt(encrypted.encode()).decode()
            value = json.loads(raw)
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise ValueError("alert channel configuration cannot be decrypted") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid alert channel configuration")
        return value

    def _public_rule(self, row: dict) -> dict:
        channels = self._decrypt_channels(row["channels_encrypted"])
        return {
            "id": row["id"],
            "owner_id": row["owner_id"],
            "monitor_target_id": row["monitor_target_id"],
            "name": row["name"],
            "rule_type": row["rule_type"],
            "threshold": row["threshold"],
            "asin": row["asin"],
            "geo_profile_id": row["geo_profile_id"],
            "channels": {
                "email_count": len(channels.get("emails", [])),
                "emails": channels.get("emails", []),
                "has_slack": bool(channels.get("slack_webhook_url")),
                "has_webhook": bool(channels.get("webhook_url")),
            },
            "cooldown_minutes": row["cooldown_minutes"],
            "enabled": row["enabled"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _mask_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}/***"
