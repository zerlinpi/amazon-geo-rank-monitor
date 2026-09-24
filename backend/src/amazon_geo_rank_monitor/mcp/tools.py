from __future__ import annotations

from amazon_geo_rank_monitor.application.rank_application import (
    enqueue_monitor,
    execute_rank_check,
    serialize_execution_result,
)


class RankMcpTools:
    def __init__(self, *, services, owner_id: str) -> None:
        self._services = services
        self._owner_id = owner_id

    async def check_rank(
        self,
        *,
        marketplace: str,
        keyword: str,
        asins: list[str],
        geo_profile_ids: list[str],
        search_depth: int = 100,
        provider_mode: str = "managed",
    ) -> dict:
        result = await execute_rank_check(
            services=self._services,
            owner_id=self._owner_id,
            marketplace=marketplace,
            keyword=keyword,
            asins=asins,
            geo_profile_ids=geo_profile_ids,
            search_depth=search_depth,
            provider_mode=provider_mode,
        )
        return serialize_execution_result(result)

    def list_geo_profiles(self) -> list[dict]:
        return self._services.geo_repository.list(owner_id=self._owner_id)

    def create_monitor(
        self,
        *,
        name: str,
        marketplace: str,
        keyword: str,
        asins: list[str],
        geo_profile_ids: list[str],
        search_depth: int = 100,
        provider_mode: str = "managed",
        schedule: str | None = None,
    ) -> dict:
        return self._services.monitor_repository.create(
            owner_id=self._owner_id,
            name=name,
            marketplace=marketplace,
            keyword=keyword,
            asins=asins,
            geo_profile_ids=geo_profile_ids,
            search_depth=search_depth,
            provider_mode=provider_mode,
            schedule=schedule,
        )

    def run_monitor(self, *, monitor_id: str) -> dict:
        monitor = self._services.monitor_repository.get(
            monitor_id,
            owner_id=self._owner_id,
        )
        if monitor is None:
            raise KeyError(f"monitor not found: {monitor_id}")
        return enqueue_monitor(
            services=self._services,
            owner_id=self._owner_id,
            monitor=monitor,
        )

    def get_rank_run(self, *, run_id: str) -> dict:
        return self._services.rank_repository.get_run(
            run_id,
            owner_id=self._owner_id,
        )

    def get_rank_history(self, *, limit: int = 50) -> list[dict]:
        return self._services.rank_repository.list_runs(
            owner_id=self._owner_id,
            limit=limit,
        )

    def get_credit_balance(self) -> dict:
        billing = getattr(self._services, "billing_repository", None)
        if billing is None:
            raise RuntimeError("billing is unavailable")
        return billing.get_balance(self._owner_id)
