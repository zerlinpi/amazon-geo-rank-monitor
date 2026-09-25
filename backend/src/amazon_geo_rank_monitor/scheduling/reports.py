from __future__ import annotations

from datetime import UTC, datetime

from .cron import latest_due_time


class ReportScheduler:
    """Dispatch at most one report for each schedule's latest due cron slot."""

    def __init__(self, *, services) -> None:
        self._services = services

    def run_once(self, *, now: datetime | None = None) -> list[dict]:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        outcomes: list[dict] = []

        for schedule in self._services.report_repository.list_scheduled():
            try:
                due_at = latest_due_time(
                    schedule["schedule"],
                    now=current,
                )
                created_at = schedule["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                created_minute = created_at.astimezone(UTC).replace(
                    second=0,
                    microsecond=0,
                )
                if due_at < created_minute:
                    continue

                delivery = self._services.reports.dispatch_schedule(
                    owner_id=schedule["owner_id"],
                    schedule_id=schedule["id"],
                    scheduled_for=due_at,
                )
                if delivery is None:
                    continue
                outcomes.append(
                    {
                        "schedule_id": schedule["id"],
                        "due_at": due_at,
                        "delivery_id": delivery["id"],
                        "delivery_status": delivery["status"],
                    }
                )
            except Exception as exc:
                outcomes.append(
                    {
                        "schedule_id": schedule["id"],
                        "error": str(exc),
                    }
                )
        return outcomes
