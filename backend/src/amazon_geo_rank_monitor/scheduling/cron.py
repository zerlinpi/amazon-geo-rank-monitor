from __future__ import annotations

from datetime import UTC, datetime

from croniter import croniter


def normalize_schedule(value: str | None) -> str | None:
    if value is None:
        return None
    expression = " ".join(value.split())
    if not expression:
        return None
    if len(expression.split()) != 5 or not croniter.is_valid(expression):
        raise ValueError("schedule must be a valid 5-field cron expression in UTC")
    return expression


def latest_due_time(expression: str, *, now: datetime | None = None) -> datetime:
    schedule = normalize_schedule(expression)
    if schedule is None:
        raise ValueError("schedule is required")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    inclusive_base = current.replace(second=59, microsecond=999999)
    due = croniter(schedule, inclusive_base).get_prev(datetime)
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due.astimezone(UTC)
