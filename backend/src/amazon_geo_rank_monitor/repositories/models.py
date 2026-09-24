from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoProfileRow(Base):
    __tablename__ = "geo_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_country: Mapped[str] = mapped_column(String(8), nullable=False)
    ip_state: Mapped[str | None] = mapped_column(String(128))
    ip_city: Mapped[str | None] = mapped_column(String(128))
    ip_postal_code: Mapped[str | None] = mapped_column(String(32))
    delivery_country: Mapped[str] = mapped_column(String(8), nullable=False)
    delivery_postal_code: Mapped[str] = mapped_column(String(32), nullable=False)
    device: Mapped[str] = mapped_column(String(16), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MonitorTargetRow(Base):
    __tablename__ = "monitor_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(128), nullable=False)
    keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    search_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="managed")
    schedule: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MonitorTargetAsinRow(Base):
    __tablename__ = "monitor_target_asins"
    __table_args__ = (
        UniqueConstraint("monitor_target_id", "asin", name="uq_monitor_asin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_target_id: Mapped[str] = mapped_column(
        ForeignKey("monitor_targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asin: Mapped[str] = mapped_column(String(32), nullable=False)


class MonitorTargetGeoRow(Base):
    __tablename__ = "monitor_target_geos"
    __table_args__ = (
        UniqueConstraint("monitor_target_id", "geo_profile_id", name="uq_monitor_geo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_target_id: Mapped[str] = mapped_column(
        ForeignKey("monitor_targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    geo_profile_id: Mapped[str] = mapped_column(
        ForeignKey("geo_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )


class RankRunRow(Base):
    __tablename__ = "rank_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    marketplace: Mapped[str] = mapped_column(String(128), nullable=False)
    keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    requested_probe_count: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_probe_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    observations: Mapped[list[RankObservationRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list[RankSnapshotRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RankObservationRow(Base):
    __tablename__ = "rank_observations"
    __table_args__ = (
        UniqueConstraint(
            "rank_run_id",
            "asin",
            "geo_profile_id",
            "provider",
            "verification_level",
            name="uq_rank_observation_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank_run_id: Mapped[str] = mapped_column(
        ForeignKey("rank_runs.id", ondelete="CASCADE")
    )
    asin: Mapped[str] = mapped_column(String(32), nullable=False)
    geo_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    organic_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    absolute_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sponsored_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    raw_result_reference: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[RankRunRow] = relationship(back_populates="observations")


class RankSnapshotRow(Base):
    __tablename__ = "rank_snapshots"
    __table_args__ = (
        UniqueConstraint("rank_run_id", "asin", name="uq_rank_snapshot_run_asin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank_run_id: Mapped[str] = mapped_column(
        ForeignKey("rank_runs.id", ondelete="CASCADE")
    )
    asin: Mapped[str] = mapped_column(String(32), nullable=False)
    weighted_rank: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    found_weight: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    missing_weight: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    run: Mapped[RankRunRow] = relationship(back_populates="snapshots")


class RankJobRow(Base):
    __tablename__ = "rank_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    monitor_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
