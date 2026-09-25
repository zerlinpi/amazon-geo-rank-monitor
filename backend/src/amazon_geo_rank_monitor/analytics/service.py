from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO


class AnalyticsService:
    def __init__(self, *, repository, monitor_repository) -> None:
        self._repository = repository
        self._monitors = monitor_repository

    def trend(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int = 168,
        asin: str | None = None,
        geo_profile_id: str | None = None,
        until: datetime | None = None,
    ) -> dict:
        monitor = self._monitor(owner_id, monitor_target_id)
        start, end = self._window(hours=hours, until=until)
        normalized_asin = asin.strip().upper() if asin else None
        if normalized_asin and normalized_asin not in monitor["asins"]:
            raise ValueError("ASIN is not part of this monitor")
        if (
            geo_profile_id
            and geo_profile_id not in monitor["geo_profile_ids"]
        ):
            raise ValueError("geo profile is not part of this monitor")

        aggregate = self._repository.aggregate_points(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            since=start,
            until=end,
            asin=normalized_asin,
        )
        geo = self._repository.geo_points(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            since=start,
            until=end,
            asin=normalized_asin,
            geo_profile_id=geo_profile_id,
        )
        return {
            "monitor": self._monitor_metadata(monitor),
            "window": {
                "start": start,
                "end": end,
                "hours": hours,
            },
            "aggregate": aggregate,
            "geo": geo,
        }

    def summary(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int = 168,
        until: datetime | None = None,
    ) -> dict:
        data = self.trend(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            hours=hours,
            until=until,
        )
        aggregate_groups: dict[str, list[dict]] = defaultdict(list)
        for point in data["aggregate"]:
            aggregate_groups[point["asin"]].append(point)

        asin_summaries = []
        for asin, points in sorted(aggregate_groups.items()):
            ranks = [Decimal(str(point["weighted_rank"])) for point in points]
            confidences = [
                Decimal(str(point["confidence"]))
                for point in points
            ]
            found_ratios = []
            for point in points:
                found = Decimal(str(point["found_weight"]))
                missing = Decimal(str(point["missing_weight"]))
                total = found + missing
                found_ratios.append(
                    found / total if total > 0 else Decimal("0")
                )
            first = ranks[0]
            latest = ranks[-1]
            count = Decimal(len(ranks))
            asin_summaries.append(
                {
                    "asin": asin,
                    "run_count": len(ranks),
                    "first_rank": first,
                    "latest_rank": latest,
                    "change": latest - first,
                    "best_rank": min(ranks),
                    "worst_rank": max(ranks),
                    "average_rank": sum(ranks) / count,
                    "average_confidence": (
                        sum(confidences) / Decimal(len(confidences))
                    ),
                    "average_found_rate": (
                        sum(found_ratios) / Decimal(len(found_ratios))
                    ),
                }
            )

        geo_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for point in data["geo"]:
            geo_groups[
                (point["asin"], point["geo_profile_id"])
            ].append(point)

        geo_summaries = []
        for (asin, geo_id), points in sorted(geo_groups.items()):
            ranks = [
                Decimal(str(point["effective_rank"]))
                for point in points
            ]
            found_count = sum(1 for point in points if point["found"])
            geo_summaries.append(
                {
                    "asin": asin,
                    "geo_profile_id": geo_id,
                    "observation_count": len(points),
                    "found_count": found_count,
                    "found_rate": (
                        Decimal(found_count) / Decimal(len(points))
                    ),
                    "best_effective_rank": min(ranks),
                    "worst_effective_rank": max(ranks),
                    "average_effective_rank": (
                        sum(ranks) / Decimal(len(ranks))
                    ),
                }
            )

        unique_runs = {
            point["run_id"]
            for point in data["aggregate"]
        }
        return {
            "monitor": data["monitor"],
            "window": data["window"],
            "run_count": len(unique_runs),
            "asins": asin_summaries,
            "geos": geo_summaries,
        }

    def export_csv(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int = 168,
        granularity: str = "aggregate",
        until: datetime | None = None,
    ) -> tuple[str, str]:
        if granularity not in {"aggregate", "geo"}:
            raise ValueError("granularity must be aggregate or geo")
        data = self.trend(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            hours=hours,
            until=until,
        )
        output = StringIO()
        if granularity == "aggregate":
            fieldnames = [
                "monitor_id",
                "monitor_name",
                "marketplace",
                "keyword",
                "run_id",
                "completed_at",
                "run_status",
                "asin",
                "weighted_rank",
                "found_weight",
                "missing_weight",
                "confidence",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for point in data["aggregate"]:
                writer.writerow(
                    {
                        "monitor_id": data["monitor"]["id"],
                        "monitor_name": data["monitor"]["name"],
                        "marketplace": data["monitor"]["marketplace"],
                        "keyword": data["monitor"]["keyword"],
                        **point,
                    }
                )
        else:
            fieldnames = [
                "monitor_id",
                "monitor_name",
                "marketplace",
                "keyword",
                "run_id",
                "completed_at",
                "run_status",
                "asin",
                "geo_profile_id",
                "found",
                "organic_rank",
                "absolute_rank",
                "sponsored_rank",
                "effective_rank",
                "provider",
                "verification_level",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for point in data["geo"]:
                writer.writerow(
                    {
                        "monitor_id": data["monitor"]["id"],
                        "monitor_name": data["monitor"]["name"],
                        "marketplace": data["monitor"]["marketplace"],
                        "keyword": data["monitor"]["keyword"],
                        **point,
                    }
                )

        safe_name = "".join(
            char if char.isalnum() or char in "-_" else "-"
            for char in data["monitor"]["name"]
        ).strip("-") or "monitor"
        filename = (
            f"{safe_name}-{granularity}-"
            f"{data['window']['end'].date().isoformat()}.csv"
        )
        return output.getvalue(), filename

    def _monitor(self, owner_id: str, monitor_target_id: str) -> dict:
        monitor = self._monitors.get(
            monitor_target_id,
            owner_id=owner_id,
        )
        if monitor is None:
            raise KeyError("monitor not found")
        return monitor

    @staticmethod
    def _monitor_metadata(monitor: dict) -> dict:
        return {
            "id": monitor["id"],
            "name": monitor["name"],
            "marketplace": monitor["marketplace"],
            "keyword": monitor["keyword"],
            "asins": monitor["asins"],
            "geo_profile_ids": monitor["geo_profile_ids"],
        }

    @staticmethod
    def _window(
        *,
        hours: int,
        until: datetime | None,
    ) -> tuple[datetime, datetime]:
        if hours < 1 or hours > 8760:
            raise ValueError("hours must be between 1 and 8760")
        end = until or datetime.now(UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        end = end.astimezone(UTC)
        return end - timedelta(hours=hours), end
