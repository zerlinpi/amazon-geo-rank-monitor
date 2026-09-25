from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import (
    RankAlertDeliveryRow,
    RankAlertEventRow,
    RankAlertRuleRow,
)


class AlertRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self._dialect_name = engine.dialect.name

    def create_rule(
        self,
        *,
        owner_id: str,
        monitor_target_id: str | None,
        name: str,
        rule_type: str,
        threshold: Decimal | None,
        asin: str | None,
        geo_profile_id: str | None,
        channels_encrypted: str,
        cooldown_minutes: int,
        enabled: bool,
    ) -> dict:
        row = RankAlertRuleRow(
            id=str(uuid4()),
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            name=name,
            rule_type=rule_type,
            threshold=threshold,
            asin=asin,
            geo_profile_id=geo_profile_id,
            channels_encrypted=channels_encrypted,
            cooldown_minutes=cooldown_minutes,
            enabled=enabled,
        )
        with self._sessions.begin() as session:
            session.add(row)
            session.flush()
            return self._serialize_rule(row)

    def get_rule(self, *, owner_id: str, rule_id: str) -> dict:
        with self._sessions() as session:
            row = session.scalar(
                select(RankAlertRuleRow).where(
                    RankAlertRuleRow.id == rule_id,
                    RankAlertRuleRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError("alert rule not found")
            return self._serialize_rule(row)

    def list_rules(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RankAlertRuleRow)
                .where(
                    RankAlertRuleRow.owner_id == owner_id,
                    RankAlertRuleRow.deleted_at.is_(None),
                )
                .order_by(RankAlertRuleRow.created_at, RankAlertRuleRow.id)
            ).all()
            return [self._serialize_rule(row) for row in rows]

    def list_enabled_for_monitor(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
    ) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RankAlertRuleRow)
                .where(
                    RankAlertRuleRow.owner_id == owner_id,
                    RankAlertRuleRow.enabled.is_(True),
                    RankAlertRuleRow.deleted_at.is_(None),
                )
                .order_by(RankAlertRuleRow.created_at, RankAlertRuleRow.id)
            ).all()
            return [
                self._serialize_rule(row)
                for row in rows
                if row.monitor_target_id in {None, monitor_target_id}
            ]

    def update_rule(
        self,
        *,
        owner_id: str,
        rule_id: str,
        changes: dict,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(RankAlertRuleRow).where(
                    RankAlertRuleRow.id == rule_id,
                    RankAlertRuleRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError("alert rule not found")
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._serialize_rule(row)

    def delete_rule(self, *, owner_id: str, rule_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(RankAlertRuleRow).where(
                    RankAlertRuleRow.id == rule_id,
                    RankAlertRuleRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError("alert rule not found")
            row.enabled = False
            row.deleted_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)

    def cooldown_active(
        self,
        *,
        rule_id: str,
        asin: str,
        geo_profile_id: str | None,
        event_type: str,
        cooldown_minutes: int,
    ) -> bool:
        cutoff = datetime.now(UTC) - timedelta(minutes=max(cooldown_minutes, 0))
        with self._sessions() as session:
            statement = select(RankAlertEventRow.id).where(
                RankAlertEventRow.rule_id == rule_id,
                RankAlertEventRow.asin == asin,
                RankAlertEventRow.event_type == event_type,
                RankAlertEventRow.created_at >= cutoff,
            )
            if geo_profile_id is None:
                statement = statement.where(
                    RankAlertEventRow.geo_profile_id.is_(None)
                )
            else:
                statement = statement.where(
                    RankAlertEventRow.geo_profile_id == geo_profile_id
                )
            return session.scalar(statement.limit(1)) is not None

    def create_event(
        self,
        *,
        owner_id: str,
        rule_id: str,
        monitor_target_id: str,
        run_id: str,
        asin: str,
        geo_profile_id: str | None,
        event_type: str,
        fingerprint: str,
        previous_value: Decimal | None,
        current_value: Decimal | None,
        details: dict,
    ) -> dict | None:
        row = RankAlertEventRow(
            id=str(uuid4()),
            owner_id=owner_id,
            rule_id=rule_id,
            monitor_target_id=monitor_target_id,
            run_id=run_id,
            asin=asin,
            geo_profile_id=geo_profile_id,
            event_type=event_type,
            fingerprint=fingerprint,
            previous_value=previous_value,
            current_value=current_value,
            details=details,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
                session.flush()
                return self._serialize_event(row)
        except IntegrityError:
            return None

    def create_event_if_not_cooling(
        self,
        *,
        owner_id: str,
        rule_id: str,
        monitor_target_id: str,
        run_id: str,
        asin: str,
        geo_profile_id: str | None,
        event_type: str,
        fingerprint: str,
        previous_value: Decimal | None,
        current_value: Decimal | None,
        details: dict,
        cooldown_minutes: int,
    ) -> dict | None:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=max(cooldown_minutes, 0))
        try:
            with self._sessions.begin() as session:
                rule_statement = select(RankAlertRuleRow.id).where(
                    RankAlertRuleRow.id == rule_id,
                    RankAlertRuleRow.owner_id == owner_id,
                    RankAlertRuleRow.enabled.is_(True),
                    RankAlertRuleRow.deleted_at.is_(None),
                )
                if self._dialect_name == "postgresql":
                    rule_statement = rule_statement.with_for_update()
                if session.scalar(rule_statement) is None:
                    return None

                if cooldown_minutes > 0:
                    recent_statement = select(RankAlertEventRow.id).where(
                        RankAlertEventRow.rule_id == rule_id,
                        RankAlertEventRow.asin == asin,
                        RankAlertEventRow.event_type == event_type,
                        RankAlertEventRow.created_at >= cutoff,
                    )
                    if geo_profile_id is None:
                        recent_statement = recent_statement.where(
                            RankAlertEventRow.geo_profile_id.is_(None)
                        )
                    else:
                        recent_statement = recent_statement.where(
                            RankAlertEventRow.geo_profile_id == geo_profile_id
                        )
                    if session.scalar(recent_statement.limit(1)) is not None:
                        return None

                row = RankAlertEventRow(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    rule_id=rule_id,
                    monitor_target_id=monitor_target_id,
                    run_id=run_id,
                    asin=asin,
                    geo_profile_id=geo_profile_id,
                    event_type=event_type,
                    fingerprint=fingerprint,
                    previous_value=previous_value,
                    current_value=current_value,
                    details=details,
                    created_at=now,
                )
                session.add(row)
                session.flush()
                return self._serialize_event(row)
        except IntegrityError:
            return None

    def record_delivery(
        self,
        *,
        event_id: str,
        channel_type: str,
        destination: str,
        status: str,
        error: str | None = None,
    ) -> dict:
        row = RankAlertDeliveryRow(
            id=str(uuid4()),
            event_id=event_id,
            channel_type=channel_type,
            destination=destination,
            status=status,
            error=error[:4000] if error else None,
        )
        with self._sessions.begin() as session:
            session.add(row)
            session.flush()
            return self._serialize_delivery(row)

    def list_events(
        self,
        *,
        owner_id: str,
        limit: int = 100,
    ) -> list[dict]:
        with self._sessions() as session:
            events = session.scalars(
                select(RankAlertEventRow)
                .where(RankAlertEventRow.owner_id == owner_id)
                .order_by(RankAlertEventRow.created_at.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
            result = []
            for event in events:
                item = self._serialize_event(event)
                deliveries = session.scalars(
                    select(RankAlertDeliveryRow)
                    .where(RankAlertDeliveryRow.event_id == event.id)
                    .order_by(RankAlertDeliveryRow.attempted_at)
                ).all()
                item["deliveries"] = [
                    self._serialize_delivery(row) for row in deliveries
                ]
                result.append(item)
            return result

    @staticmethod
    def _serialize_rule(row: RankAlertRuleRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "monitor_target_id": row.monitor_target_id,
            "name": row.name,
            "rule_type": row.rule_type,
            "threshold": row.threshold,
            "asin": row.asin,
            "geo_profile_id": row.geo_profile_id,
            "channels_encrypted": row.channels_encrypted,
            "cooldown_minutes": row.cooldown_minutes,
            "enabled": row.enabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    @staticmethod
    def _serialize_event(row: RankAlertEventRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "rule_id": row.rule_id,
            "monitor_target_id": row.monitor_target_id,
            "run_id": row.run_id,
            "asin": row.asin,
            "geo_profile_id": row.geo_profile_id,
            "event_type": row.event_type,
            "fingerprint": row.fingerprint,
            "previous_value": row.previous_value,
            "current_value": row.current_value,
            "details": row.details,
            "created_at": row.created_at,
        }

    @staticmethod
    def _serialize_delivery(row: RankAlertDeliveryRow) -> dict:
        return {
            "id": row.id,
            "event_id": row.event_id,
            "channel_type": row.channel_type,
            "destination": row.destination,
            "status": row.status,
            "error": row.error,
            "attempted_at": row.attempted_at,
        }
