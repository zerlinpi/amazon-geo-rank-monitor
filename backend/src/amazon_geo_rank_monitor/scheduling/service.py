from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from amazon_geo_rank_monitor.application.rank_application import enqueue_monitor

from .cron import latest_due_time


def scheduled_job_id(monitor_id: str, due_at: datetime) -> str:
    normalized = due_at.astimezone(UTC).replace(second=0, microsecond=0)
    return str(uuid5(NAMESPACE_URL, f"agrm:{monitor_id}:{normalized.isoformat()}"))


class MonitorScheduler:
    """Dispatch at most one idempotent job for each monitor's latest due cron slot."""

    def __init__(self, *, services) -> None:
        self._services = services

    def run_once(self, *, now: datetime | None = None) -> list[dict]:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        outcomes: list[dict] = []

        for monitor in self._services.monitor_repository.list_scheduled():
            try:
                due_at = latest_due_time(monitor["schedule"], now=current)
                created_at = monitor["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                created_minute = created_at.astimezone(UTC).replace(
                    second=0,
                    microsecond=0,
                )
                if due_at < created_minute:
                    continue

                job = enqueue_monitor(
                    services=self._services,
                    owner_id=monitor["owner_id"],
                    monitor=monitor,
                    job_id=scheduled_job_id(monitor["id"], due_at),
                )
                outcomes.append(
                    {
                        "monitor_id": monitor["id"],
                        "due_at": due_at,
                        "job_id": job["id"],
                        "job_status": job["status"],
                    }
                )
            except Exception as exc:
                outcomes.append(
                    {
                        "monitor_id": monitor["id"],
                        "error": str(exc),
                    }
                )
        return outcomes
