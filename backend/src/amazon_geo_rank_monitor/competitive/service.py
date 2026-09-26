from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import fmean


class CompetitiveIntelligenceService:
    def __init__(self, *, repository, monitor_repository) -> None:
        self._repository = repository
        self._monitors = monitor_repository

    def capture_probe(
        self,
        *,
        owner_id: str | None,
        run_id: str,
        geo_profile_id: str,
        result,
        search_depth: int,
        probe_source: str,
        cache_age_seconds: int | None,
        observed_at: datetime,
    ) -> None:
        if owner_id is None:
            return
        products: dict[str, dict] = {}

        def record(items, field: str) -> None:
            for item in items:
                if item.position > search_depth:
                    continue
                asin = item.asin.strip().upper()
                if not asin:
                    continue
                row = products.setdefault(
                    asin,
                    {
                        "asin": asin,
                        "title": item.title,
                        "organic_position": None,
                        "sponsored_position": None,
                        "absolute_position": None,
                    },
                )
                current = row[field]
                if current is None or item.position < current:
                    row[field] = item.position
                if not row.get("title") and item.title:
                    row["title"] = item.title

        record(result.organic_products, "organic_position")
        record(result.sponsored_products, "sponsored_position")
        record(result.absolute_products, "absolute_position")
        self._repository.save_probe(
            owner_id=owner_id,
            run_id=run_id,
            geo_profile_id=geo_profile_id,
            rows=list(products.values()),
            probe_source=probe_source,
            cache_age_seconds=cache_age_seconds,
            observed_at=observed_at,
        )

    def summary(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int = 168,
        top_n: int = 20,
        limit: int = 50,
        include_tracked: bool = False,
    ) -> dict:
        monitor, points, start, end = self._load(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            hours=hours,
        )
        if top_n < 1 or top_n > 100:
            raise ValueError("top_n must be between 1 and 100")
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")

        tracked = set(monitor["asins"])
        probe_ids = {(p["run_id"], p["geo_profile_id"]) for p in points}
        organic_total = sum(
            1
            for p in points
            if p["organic_position"] is not None
            and p["organic_position"] <= top_n
        )
        sponsored_total = sum(
            1
            for p in points
            if p["sponsored_position"] is not None
            and p["sponsored_position"] <= top_n
        )

        by_asin: dict[str, list[dict]] = defaultdict(list)
        for point in points:
            by_asin[point["asin"]].append(point)

        competitors = []
        for asin, rows in by_asin.items():
            if not include_tracked and asin in tracked:
                continue
            organic_rows = [
                row
                for row in rows
                if row["organic_position"] is not None
                and row["organic_position"] <= top_n
            ]
            sponsored_rows = [
                row
                for row in rows
                if row["sponsored_position"] is not None
                and row["sponsored_position"] <= top_n
            ]
            if not organic_rows and not sponsored_rows:
                continue

            organic_positions = [row["organic_position"] for row in organic_rows]
            sponsored_positions = [row["sponsored_position"] for row in sponsored_rows]
            run_averages: list[tuple[datetime, str, float]] = []
            per_run: dict[str, list[dict]] = defaultdict(list)
            for row in organic_rows:
                per_run[row["run_id"]].append(row)
            for run_id, run_rows in per_run.items():
                completed_at = max(self._utc(row["completed_at"]) for row in run_rows)
                run_averages.append(
                    (
                        completed_at,
                        run_id,
                        fmean(row["organic_position"] for row in run_rows),
                    )
                )
            run_averages.sort()
            latest_rank = run_averages[-1][2] if run_averages else None
            previous_rank = run_averages[-2][2] if len(run_averages) > 1 else None
            latest_row = max(
                rows,
                key=lambda row: (
                    self._utc(row["completed_at"]),
                    self._utc(row["observed_at"]),
                ),
            )
            organic_probe_ids = {
                (row["run_id"], row["geo_profile_id"]) for row in organic_rows
            }
            sponsored_probe_ids = {
                (row["run_id"], row["geo_profile_id"]) for row in sponsored_rows
            }
            competitors.append(
                {
                    "asin": asin,
                    "title": latest_row["title"],
                    "tracked": asin in tracked,
                    "organic_appearances": len(organic_rows),
                    "sponsored_appearances": len(sponsored_rows),
                    "organic_sov_pct": self._pct(len(organic_rows), organic_total),
                    "sponsored_sov_pct": self._pct(
                        len(sponsored_rows),
                        sponsored_total,
                    ),
                    "organic_probe_coverage_pct": self._pct(
                        len(organic_probe_ids),
                        len(probe_ids),
                    ),
                    "sponsored_probe_coverage_pct": self._pct(
                        len(sponsored_probe_ids),
                        len(probe_ids),
                    ),
                    "best_organic_rank": (
                        min(organic_positions) if organic_positions else None
                    ),
                    "average_organic_rank": (
                        round(fmean(organic_positions), 2)
                        if organic_positions
                        else None
                    ),
                    "best_sponsored_rank": (
                        min(sponsored_positions) if sponsored_positions else None
                    ),
                    "average_sponsored_rank": (
                        round(fmean(sponsored_positions), 2)
                        if sponsored_positions
                        else None
                    ),
                    "latest_organic_rank": (
                        round(latest_rank, 2) if latest_rank is not None else None
                    ),
                    "organic_rank_change": (
                        round(latest_rank - previous_rank, 2)
                        if latest_rank is not None and previous_rank is not None
                        else None
                    ),
                    "run_count": len({row["run_id"] for row in rows}),
                    "geo_count": len({row["geo_profile_id"] for row in rows}),
                }
            )

        competitors.sort(
            key=lambda row: (
                -row["organic_sov_pct"],
                -row["sponsored_sov_pct"],
                row["average_organic_rank"]
                if row["average_organic_rank"] is not None
                else 10_000,
                row["asin"],
            )
        )
        return {
            "monitor": {
                "id": monitor["id"],
                "name": monitor["name"],
                "marketplace": monitor["marketplace"],
                "keyword": monitor["keyword"],
                "tracked_asins": monitor["asins"],
            },
            "window": {
                "start": start,
                "end": end,
                "hours": hours,
                "top_n": top_n,
            },
            "probe_count": len(probe_ids),
            "organic_slot_count": organic_total,
            "sponsored_slot_count": sponsored_total,
            "competitors": competitors[:limit],
            "geo_leaders": self._geo_leaders(
                points=points,
                tracked=tracked,
                top_n=top_n,
                include_tracked=include_tracked,
            ),
        }

    def trend(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int = 168,
        top_n: int = 20,
        asins: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        monitor, points, start, end = self._load(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            hours=hours,
        )
        if top_n < 1 or top_n > 100:
            raise ValueError("top_n must be between 1 and 100")
        requested = {
            asin.strip().upper()
            for asin in (asins or [])
            if asin.strip()
        }
        if not requested:
            summary = self.summary(
                owner_id=owner_id,
                monitor_target_id=monitor_target_id,
                hours=hours,
                top_n=top_n,
                limit=limit,
                include_tracked=False,
            )
            requested = {row["asin"] for row in summary["competitors"]}

        run_probes: dict[str, set[str]] = defaultdict(set)
        run_times: dict[str, datetime] = {}
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for point in points:
            run_id = point["run_id"]
            run_probes[run_id].add(point["geo_profile_id"])
            run_times[run_id] = self._utc(point["completed_at"])
            if point["asin"] in requested:
                grouped[(run_id, point["asin"])].append(point)

        series = []
        for (run_id, asin), rows in grouped.items():
            organic = [
                row["organic_position"]
                for row in rows
                if row["organic_position"] is not None
                and row["organic_position"] <= top_n
            ]
            sponsored = [
                row["sponsored_position"]
                for row in rows
                if row["sponsored_position"] is not None
                and row["sponsored_position"] <= top_n
            ]
            organic_geos = {
                row["geo_profile_id"]
                for row in rows
                if row["organic_position"] is not None
                and row["organic_position"] <= top_n
            }
            if not organic and not sponsored:
                continue
            series.append(
                {
                    "run_id": run_id,
                    "completed_at": run_times[run_id],
                    "asin": asin,
                    "average_organic_rank": (
                        round(fmean(organic), 2) if organic else None
                    ),
                    "best_organic_rank": min(organic) if organic else None,
                    "organic_probe_coverage_pct": self._pct(
                        len(organic_geos),
                        len(run_probes[run_id]),
                    ),
                    "sponsored_appearances": len(sponsored),
                }
            )
        series.sort(key=lambda row: (self._utc(row["completed_at"]), row["asin"]))
        return {
            "monitor": {
                "id": monitor["id"],
                "name": monitor["name"],
                "marketplace": monitor["marketplace"],
                "keyword": monitor["keyword"],
            },
            "window": {
                "start": start,
                "end": end,
                "hours": hours,
                "top_n": top_n,
            },
            "asins": sorted(requested),
            "series": series,
        }

    def _load(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        hours: int,
    ) -> tuple[dict, list[dict], datetime, datetime]:
        if hours < 1 or hours > 8760:
            raise ValueError("hours must be between 1 and 8760")
        monitor = self._monitors.get(monitor_target_id, owner_id=owner_id)
        if monitor is None:
            raise KeyError("monitor not found")
        end = datetime.now(UTC)
        start = end - timedelta(hours=hours)
        points = self._repository.monitor_points(
            owner_id=owner_id,
            monitor_target_id=monitor_target_id,
            since=start,
            until=end,
        )
        return monitor, points, start, end

    @classmethod
    def _geo_leaders(
        cls,
        *,
        points: list[dict],
        tracked: set[str],
        top_n: int,
        include_tracked: bool,
    ) -> list[dict]:
        by_geo: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in points:
            if not include_tracked and row["asin"] in tracked:
                continue
            position = row["organic_position"]
            if position is None or position > top_n:
                continue
            by_geo[row["geo_profile_id"]][row["asin"]].append(position)

        result = []
        for geo_id, asins in sorted(by_geo.items()):
            leaders = [
                {
                    "asin": asin,
                    "appearances": len(positions),
                    "average_organic_rank": round(fmean(positions), 2),
                    "best_organic_rank": min(positions),
                }
                for asin, positions in asins.items()
            ]
            leaders.sort(
                key=lambda row: (
                    -row["appearances"],
                    row["average_organic_rank"],
                    row["asin"],
                )
            )
            result.append(
                {
                    "geo_profile_id": geo_id,
                    "leaders": leaders[:5],
                }
            )
        return result

    @staticmethod
    def _pct(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((numerator / denominator) * 100, 2)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
