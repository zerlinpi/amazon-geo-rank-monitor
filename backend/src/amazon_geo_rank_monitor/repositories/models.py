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


class RankRunRow(Base):
    __tablename__ = "rank_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
