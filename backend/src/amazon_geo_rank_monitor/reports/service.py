from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken

from amazon_geo_rank_monitor.notifications.email import EmailAttachment
from amazon_geo_rank_monitor.scheduling.cron import normalize_schedule


class ReportService:
    def __init__(
        self,
        *,
        repository,
        analytics,
        monitor_repository,
        email_sender,
        encryption_key: str,
    ) -> None:
        if not encryption_key:
            raise ValueError("report encryption key is required")
        digest = hashlib.sha256(encryption_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._repository = repository
        self._analytics = analytics
        self._monitors = monitor_repository
        self._email = email_sender

    def create_schedule(
        self,
        *,
        owner_id: str,
        name: str,
        monitor_target_ids: list[str],
        recipients: list[str],
        schedule: str,
        lookback_hours: int,
        include_csv: bool,
        enabled: bool = True,
    ) -> dict:
        normalized = self._validate_schedule_payload(
            owner_id=owner_id,
            name=name,
            monitor_target_ids=monitor_target_ids,
            recipients=recipients,
            schedule=schedule,
            lookback_hours=lookback_hours,
        )
        row = self._repository.create_schedule(
            owner_id=owner_id,
            name=normalized["name"],
            monitor_target_ids=normalized["monitor_target_ids"],
            recipients_encrypted=self._encrypt_recipients(
                normalized["recipients"]
            ),
            schedule=normalized["schedule"],
            lookback_hours=normalized["lookback_hours"],
            include_csv=bool(include_csv),
            enabled=bool(enabled),
        )
        return self._public_schedule(row)

    def update_schedule(
        self,
        *,
        owner_id: str,
        schedule_id: str,
        changes: dict,
    ) -> dict:
        existing = self._repository.get_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
        )
        recipients = (
            changes["recipients"]
            if "recipients" in changes and changes["recipients"] is not None
            else self._decrypt_recipients(existing["recipients_encrypted"])
        )
        normalized = self._validate_schedule_payload(
            owner_id=owner_id,
            name=changes.get("name", existing["name"]),
            monitor_target_ids=changes.get(
                "monitor_target_ids",
                existing["monitor_target_ids"],
            ),
            recipients=recipients,
            schedule=changes.get("schedule", existing["schedule"]),
            lookback_hours=changes.get(
                "lookback_hours",
                existing["lookback_hours"],
            ),
        )
        payload = {
            "name": normalized["name"],
            "monitor_target_ids": normalized["monitor_target_ids"],
            "schedule": normalized["schedule"],
            "lookback_hours": normalized["lookback_hours"],
        }
        if "recipients" in changes and changes["recipients"] is not None:
            payload["recipients_encrypted"] = self._encrypt_recipients(
                normalized["recipients"]
            )
        if "include_csv" in changes and changes["include_csv"] is not None:
            payload["include_csv"] = bool(changes["include_csv"])
        if "enabled" in changes and changes["enabled"] is not None:
            payload["enabled"] = bool(changes["enabled"])

        row = self._repository.update_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
            changes=payload,
        )
        return self._public_schedule(row)

    def list_schedules(self, *, owner_id: str) -> list[dict]:
        return [
            self._public_schedule(row)
            for row in self._repository.list_schedules(owner_id=owner_id)
        ]

    def get_schedule(self, *, owner_id: str, schedule_id: str) -> dict:
        return self._public_schedule(
            self._repository.get_schedule(
                owner_id=owner_id,
                schedule_id=schedule_id,
            )
        )

    def delete_schedule(self, *, owner_id: str, schedule_id: str) -> None:
        self._repository.delete_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
        )

    def list_deliveries(
        self,
        *,
        owner_id: str,
        limit: int = 100,
    ) -> list[dict]:
        return self._repository.list_deliveries(
            owner_id=owner_id,
            limit=limit,
        )

    def dispatch_schedule(
        self,
        *,
        owner_id: str,
        schedule_id: str,
        scheduled_for: datetime,
    ) -> dict | None:
        schedule = self._repository.get_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
        )
        if not schedule["enabled"]:
            return None

        recipients = self._decrypt_recipients(
            schedule["recipients_encrypted"]
        )
        due_at = self._utc(scheduled_for)
        subject = (
            f"{schedule['name']} · "
            f"{due_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        delivery = self._repository.reserve_delivery(
            owner_id=owner_id,
            schedule_id=schedule_id,
            scheduled_for=due_at,
            subject=subject,
            recipient_count=len(recipients),
        )
        if delivery is None:
            return None

        summaries = []
        attachments: list[EmailAttachment] = []
        try:
            for monitor_id in schedule["monitor_target_ids"]:
                summary = self._analytics.summary(
                    owner_id=owner_id,
                    monitor_target_id=monitor_id,
                    hours=schedule["lookback_hours"],
                    until=due_at,
                )
                summaries.append(summary)
                if schedule["include_csv"]:
                    csv_text, filename = self._analytics.export_csv(
                        owner_id=owner_id,
                        monitor_target_id=monitor_id,
                        hours=schedule["lookback_hours"],
                        granularity="aggregate",
                        until=due_at,
                    )
                    attachments.append(
                        EmailAttachment(
                            filename=filename,
                            content=csv_text.encode("utf-8-sig"),
                            content_type="text/csv",
                        )
                    )

            body = self._render_text_report(
                name=schedule["name"],
                scheduled_for=due_at,
                lookback_hours=schedule["lookback_hours"],
                summaries=summaries,
            )
            errors = []
            sent_count = 0
            for recipient in recipients:
                try:
                    self._email.send(
                        to=recipient,
                        subject=subject,
                        text=body,
                        attachments=attachments,
                    )
                    sent_count += 1
                except Exception as exc:
                    errors.append(f"{recipient}: {str(exc)[:500]}")

            if sent_count == len(recipients):
                status = "sent"
            elif sent_count:
                status = "partially_failed"
            else:
                status = "failed"

            return self._repository.complete_delivery(
                delivery_id=delivery["id"],
                status=status,
                sent_count=sent_count,
                summary={
                    "lookback_hours": schedule["lookback_hours"],
                    "monitors": [
                        self._summary_for_storage(item)
                        for item in summaries
                    ],
                },
                error="; ".join(errors) if errors else None,
            )
        except Exception as exc:
            return self._repository.complete_delivery(
                delivery_id=delivery["id"],
                status="failed",
                sent_count=0,
                summary={},
                error=str(exc),
            )

    def _validate_schedule_payload(
        self,
        *,
        owner_id: str,
        name: str,
        monitor_target_ids: list[str],
        recipients: list[str],
        schedule: str,
        lookback_hours: int,
    ) -> dict:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("report name is required")
        monitor_ids = list(
            dict.fromkeys(
                item.strip()
                for item in monitor_target_ids
                if item.strip()
            )
        )
        if not monitor_ids:
            raise ValueError("at least one monitor is required")
        for monitor_id in monitor_ids:
            if self._monitors.get(monitor_id, owner_id=owner_id) is None:
                raise KeyError("one or more monitors are not available")

        normalized_recipients = self._normalize_recipients(recipients)
        normalized_schedule = normalize_schedule(schedule)
        if normalized_schedule is None:
            raise ValueError("report schedule is required")
        if lookback_hours < 1 or lookback_hours > 8760:
            raise ValueError("lookback_hours must be between 1 and 8760")
        return {
            "name": normalized_name,
            "monitor_target_ids": monitor_ids,
            "recipients": normalized_recipients,
            "schedule": normalized_schedule,
            "lookback_hours": lookback_hours,
        }

    @staticmethod
    def _normalize_recipients(recipients: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(
                item.strip().lower()
                for item in recipients
                if item.strip()
            )
        )
        if not normalized:
            raise ValueError("at least one report recipient is required")
        for email in normalized:
            if (
                "@" not in email
                or email.startswith("@")
                or email.endswith("@")
            ):
                raise ValueError(f"invalid report recipient: {email}")
        return normalized

    def _encrypt_recipients(self, recipients: list[str]) -> str:
        payload = json.dumps(
            recipients,
            separators=(",", ":"),
        ).encode()
        return self._fernet.encrypt(payload).decode()

    def _decrypt_recipients(self, value: str) -> list[str]:
        try:
            payload = self._fernet.decrypt(value.encode())
            decoded = json.loads(payload)
        except (InvalidToken, json.JSONDecodeError):
            raise ValueError("report recipients cannot be decrypted") from None
        if not isinstance(decoded, list):
            raise ValueError("report recipients are invalid")
        return [str(item) for item in decoded]

    def _public_schedule(self, row: dict) -> dict:
        recipients = self._decrypt_recipients(row["recipients_encrypted"])
        return {
            "id": row["id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "monitor_target_ids": row["monitor_target_ids"],
            "recipients": recipients,
            "schedule": row["schedule"],
            "lookback_hours": row["lookback_hours"],
            "include_csv": row["include_csv"],
            "enabled": row["enabled"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _render_text_report(
        *,
        name: str,
        scheduled_for: datetime,
        lookback_hours: int,
        summaries: list[dict],
    ) -> str:
        lines = [
            name,
            "=" * len(name),
            "",
            f"Generated: {scheduled_for.isoformat()}",
            f"Window: previous {lookback_hours} hours",
            "",
        ]
        for summary in summaries:
            monitor = summary["monitor"]
            lines.extend(
                [
                    f"{monitor['name']} · {monitor['keyword']}",
                    f"Marketplace: {monitor['marketplace']}",
                    f"Completed runs: {summary['run_count']}",
                ]
            )
            if not summary["asins"]:
                lines.append("No completed rank data in this window.")
            for item in summary["asins"]:
                change = Decimal(str(item["change"]))
                direction = (
                    f"+{change} worse"
                    if change > 0
                    else f"{abs(change)} better"
                    if change < 0
                    else "no change"
                )
                lines.append(
                    " · ".join(
                        [
                            item["asin"],
                            f"latest #{item['latest_rank']}",
                            f"change {direction}",
                            f"best #{item['best_rank']}",
                            f"worst #{item['worst_rank']}",
                            (
                                "found "
                                f"{Decimal(str(item['average_found_rate'])) * 100:.1f}%"
                            ),
                        ]
                    )
                )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _summary_for_storage(summary: dict) -> dict:
        return {
            "monitor": summary["monitor"],
            "window": {
                key: (
                    value.isoformat()
                    if isinstance(value, datetime)
                    else value
                )
                for key, value in summary["window"].items()
            },
            "run_count": summary["run_count"],
            "asins": [
                {
                    key: (
                        float(value)
                        if isinstance(value, Decimal)
                        else value
                    )
                    for key, value in item.items()
                }
                for item in summary["asins"]
            ],
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
