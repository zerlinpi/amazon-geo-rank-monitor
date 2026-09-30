from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.repositories.models import SerpProbeCacheRow


class ProbeCacheRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self._insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert

    def get_fresh(
        self,
        *,
        owner_id: str,
        cache_key: str,
        now: datetime,
    ) -> dict | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                update(SerpProbeCacheRow)
                .where(SerpProbeCacheRow.owner_id == owner_id,
                       SerpProbeCacheRow.cache_key == cache_key,
                       SerpProbeCacheRow.expires_at > now)
                .values(hit_count=SerpProbeCacheRow.hit_count + 1, last_used_at=now)
                .returning(SerpProbeCacheRow)
            )
            return self._serialize(row) if row is not None else None

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
        values = dict(
            owner_id=owner_id, cache_key=cache_key, provider_mode=provider_mode,
            provider_name=provider_name, verification_level=verification_level,
            marketplace=marketplace, keyword=keyword, geo_profile_id=geo_profile_id,
            device=device, search_depth=search_depth, identity_payload=identity_payload,
            result_payload=result_payload, fetched_at=fetched_at, expires_at=expires_at,
            last_used_at=fetched_at, hit_count=0,
        )
        statement = self._insert(SerpProbeCacheRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["owner_id", "cache_key"],
            set_={key: value for key, value in values.items()
                  if key not in {"owner_id", "cache_key"}},
            where=SerpProbeCacheRow.fetched_at <= statement.excluded.fetched_at,
        ).returning(SerpProbeCacheRow)
        with self._sessions.begin() as session:
            row = session.scalar(statement)
            if row is None:  # A newer result won while this upstream request was in flight.
                row = session.get(SerpProbeCacheRow, (owner_id, cache_key))
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
