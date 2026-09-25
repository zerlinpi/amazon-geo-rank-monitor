from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, delete
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.repositories.models import SerpProbeCacheRow


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ProbeCacheRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_fresh(
        self,
        *,
        owner_id: str,
        cache_key: str,
        now: datetime,
    ) -> dict | None:
        with self._sessions.begin() as session:
            row = session.get(SerpProbeCacheRow, (owner_id, cache_key))
            if row is None or _utc(row.expires_at) <= now:
                return None
            row.hit_count += 1
            row.last_used_at = now
            session.flush()
            return self._serialize(row)

    def put(
        self,
        *,
        owner_id: str,
        cache_key: str,
        provider_mode: str,
        provider_name: str,
        verification_level: str,
        marketplace: str,
        keyword: str,
        geo_profile_id: str,
        device: str,
        search_depth: int,
        identity_payload: dict,
        result_payload: dict,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.get(SerpProbeCacheRow, (owner_id, cache_key))
            if row is None:
                row = SerpProbeCacheRow(
                    owner_id=owner_id,
                    cache_key=cache_key,
                    provider_mode=provider_mode,
                    provider_name=provider_name,
                    verification_level=verification_level,
                    marketplace=marketplace,
                    keyword=keyword,
                    geo_profile_id=geo_profile_id,
                    device=device,
                    search_depth=search_depth,
                    identity_payload=identity_payload,
                    result_payload=result_payload,
                    fetched_at=fetched_at,
                    expires_at=expires_at,
                    last_used_at=fetched_at,
                    hit_count=0,
                )
                session.add(row)
            else:
                row.provider_mode = provider_mode
                row.provider_name = provider_name
                row.verification_level = verification_level
                row.marketplace = marketplace
                row.keyword = keyword
                row.geo_profile_id = geo_profile_id
                row.device = device
                row.search_depth = search_depth
                row.identity_payload = identity_payload
                row.result_payload = result_payload
                row.fetched_at = fetched_at
                row.expires_at = expires_at
                row.last_used_at = fetched_at
                row.hit_count = 0
            session.flush()
            return self._serialize(row)

    def delete_entry(self, *, owner_id: str, cache_key: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(SerpProbeCacheRow, (owner_id, cache_key))
            if row is not None:
                session.delete(row)

    def prune_expired(self, *, before: datetime) -> int:
        with self._sessions.begin() as session:
            result = session.execute(
                delete(SerpProbeCacheRow).where(
                    SerpProbeCacheRow.expires_at < before
                )
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _serialize(row: SerpProbeCacheRow) -> dict:
        return {
            "owner_id": row.owner_id,
            "cache_key": row.cache_key,
            "provider_mode": row.provider_mode,
            "provider_name": row.provider_name,
            "verification_level": row.verification_level,
            "marketplace": row.marketplace,
            "keyword": row.keyword,
            "geo_profile_id": row.geo_profile_id,
            "device": row.device,
            "search_depth": row.search_depth,
            "identity_payload": row.identity_payload,
            "result_payload": row.result_payload,
            "fetched_at": row.fetched_at,
            "expires_at": row.expires_at,
            "last_used_at": row.last_used_at,
            "hit_count": row.hit_count,
        }
