from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from amazon_geo_rank_monitor.billing.errors import InsufficientCreditsError

from .models import (
    CreditAccountRow,
    CreditLedgerEntryRow,
    CreditPackRow,
    CreditReservationRow,
)


class BillingRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def ensure_account(self, owner_id: str) -> dict:
        with self._sessions.begin() as session:
            account = self._account_for_update(session, owner_id)
            return self._serialize_account(account)

    def get_account(self, owner_id: str) -> dict:
        with self._sessions() as session:
            account = session.get(CreditAccountRow, owner_id)
            if account is None:
                return {
                    "owner_id": owner_id,
                    "available_credits": 0,
                    "reserved_credits": 0,
                }
            return self._serialize_account(account)

    def grant(
        self,
        *,
        owner_id: str,
        amount: int,
        idempotency_key: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        if amount <= 0:
            raise ValueError("grant amount must be positive")
        with self._sessions.begin() as session:
            if self._ledger_by_key(session, idempotency_key) is not None:
                account = self._account_for_update(session, owner_id)
                return self._serialize_account(account)
            account = self._account_for_update(session, owner_id)
            account.available_credits += amount
            account.updated_at = datetime.now(UTC)
            self._add_ledger(
                session,
                owner_id=owner_id,
                entry_type="purchase",
                available_delta=amount,
                reserved_delta=0,
                idempotency_key=idempotency_key,
                reference_type=reference_type,
                reference_id=reference_id,
                metadata=metadata,
            )
            return self._serialize_account(account)

    def reserve(
        self,
        *,
        owner_id: str,
        amount: int,
        idempotency_key: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> dict:
        if amount <= 0:
            raise ValueError("reservation amount must be positive")
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(CreditReservationRow).where(
                    CreditReservationRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return self._serialize_reservation(existing)

            account = self._account_for_update(session, owner_id)
            if account.available_credits < amount:
                raise InsufficientCreditsError(
                    available=account.available_credits,
                    required=amount,
                )

            account.available_credits -= amount
            account.reserved_credits += amount
            account.updated_at = datetime.now(UTC)
            reservation = CreditReservationRow(
                id=str(uuid4()),
                owner_id=owner_id,
                amount=amount,
                settled_amount=0,
                released_amount=0,
                status="active",
                idempotency_key=idempotency_key,
                reference_type=reference_type,
                reference_id=reference_id,
            )
            session.add(reservation)
            self._add_ledger(
                session,
                owner_id=owner_id,
                entry_type="reservation",
                available_delta=-amount,
                reserved_delta=amount,
                idempotency_key=f"reserve:{idempotency_key}",
                reference_type=reference_type,
                reference_id=reference_id,
            )
            session.flush()
            return self._serialize_reservation(reservation)

    def settle(
        self,
        reservation_id: str,
        *,
        actual_amount: int,
        idempotency_key: str,
    ) -> dict:
        if actual_amount < 0:
            raise ValueError("actual amount cannot be negative")
        with self._sessions.begin() as session:
            existing_entry = self._ledger_by_key(
                session, f"settle:{idempotency_key}"
            )
            reservation = self._reservation_for_update(session, reservation_id)
            if existing_entry is not None or reservation.status != "active":
                return self._serialize_reservation(reservation)
            if actual_amount > reservation.amount:
                raise ValueError("actual amount cannot exceed reserved amount")

            account = self._account_for_update(session, reservation.owner_id)
            remainder = reservation.amount - actual_amount

            account.reserved_credits -= actual_amount
            self._add_ledger(
                session,
                owner_id=reservation.owner_id,
                entry_type="settlement",
                available_delta=0,
                reserved_delta=-actual_amount,
                idempotency_key=f"settle:{idempotency_key}",
                reference_type=reservation.reference_type,
                reference_id=reservation.reference_id,
            )

            if remainder:
                account.available_credits += remainder
                account.reserved_credits -= remainder
                self._add_ledger(
                    session,
                    owner_id=reservation.owner_id,
                    entry_type="release",
                    available_delta=remainder,
                    reserved_delta=-remainder,
                    idempotency_key=f"release-unused:{idempotency_key}",
                    reference_type=reservation.reference_type,
                    reference_id=reservation.reference_id,
                )

            account.updated_at = datetime.now(UTC)
            reservation.settled_amount = actual_amount
            reservation.released_amount = remainder
            reservation.status = "settled"
            reservation.completed_at = datetime.now(UTC)
            return self._serialize_reservation(reservation)

    def release(
        self,
        reservation_id: str,
        *,
        idempotency_key: str,
    ) -> dict:
        with self._sessions.begin() as session:
            existing_entry = self._ledger_by_key(
                session, f"release:{idempotency_key}"
            )
            reservation = self._reservation_for_update(session, reservation_id)
            if existing_entry is not None or reservation.status != "active":
                return self._serialize_reservation(reservation)

            amount = reservation.amount
            account = self._account_for_update(session, reservation.owner_id)
            account.available_credits += amount
            account.reserved_credits -= amount
            account.updated_at = datetime.now(UTC)
            self._add_ledger(
                session,
                owner_id=reservation.owner_id,
                entry_type="release",
                available_delta=amount,
                reserved_delta=-amount,
                idempotency_key=f"release:{idempotency_key}",
                reference_type=reservation.reference_type,
                reference_id=reservation.reference_id,
            )
            reservation.released_amount = amount
            reservation.status = "released"
            reservation.completed_at = datetime.now(UTC)
            return self._serialize_reservation(reservation)

    def get_reservation(self, reservation_id: str, *, owner_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(CreditReservationRow).where(
                    CreditReservationRow.id == reservation_id,
                    CreditReservationRow.owner_id == owner_id,
                )
            )
            return self._serialize_reservation(row) if row else None

    def list_ledger(self, *, owner_id: str, limit: int = 100) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(CreditLedgerEntryRow)
                .where(CreditLedgerEntryRow.owner_id == owner_id)
                .order_by(CreditLedgerEntryRow.created_at, CreditLedgerEntryRow.id)
                .limit(limit)
            ).all()
            return [self._serialize_ledger(row) for row in rows]

    def create_credit_pack(
        self,
        *,
        pack_id: str,
        name: str,
        credits: int,
        stripe_price_id: str,
        active: bool = True,
        display_order: int = 0,
    ) -> dict:
        if credits <= 0:
            raise ValueError("credit pack credits must be positive")
        with self._sessions.begin() as session:
            existing = session.get(CreditPackRow, pack_id)
            if existing is None:
                existing = CreditPackRow(
                    id=pack_id,
                    name=name,
                    credits=credits,
                    stripe_price_id=stripe_price_id,
                    active=active,
                    display_order=display_order,
                )
                session.add(existing)
            else:
                existing.name = name
                existing.credits = credits
                existing.stripe_price_id = stripe_price_id
                existing.active = active
                existing.display_order = display_order
            session.flush()
            return self._serialize_pack(existing)

    def get_credit_pack(self, pack_id: str, *, active_only: bool = True) -> dict | None:
        with self._sessions() as session:
            statement = select(CreditPackRow).where(CreditPackRow.id == pack_id)
            if active_only:
                statement = statement.where(CreditPackRow.active.is_(True))
            row = session.scalar(statement)
            return self._serialize_pack(row) if row else None

    def list_credit_packs(self, *, active_only: bool = True) -> list[dict]:
        with self._sessions() as session:
            statement = select(CreditPackRow)
            if active_only:
                statement = statement.where(CreditPackRow.active.is_(True))
            rows = session.scalars(
                statement.order_by(CreditPackRow.display_order, CreditPackRow.id)
            ).all()
            return [self._serialize_pack(row) for row in rows]

    def _account_for_update(
        self, session: Session, owner_id: str
    ) -> CreditAccountRow:
        account = session.scalar(
            select(CreditAccountRow)
            .where(CreditAccountRow.owner_id == owner_id)
            .with_for_update()
        )
        if account is None:
            account = CreditAccountRow(
                owner_id=owner_id,
                available_credits=0,
                reserved_credits=0,
            )
            session.add(account)
            session.flush()
        return account

    @staticmethod
    def _reservation_for_update(
        session: Session, reservation_id: str
    ) -> CreditReservationRow:
        reservation = session.scalar(
            select(CreditReservationRow)
            .where(CreditReservationRow.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise KeyError(f"credit reservation not found: {reservation_id}")
        return reservation

    @staticmethod
    def _ledger_by_key(
        session: Session, idempotency_key: str
    ) -> CreditLedgerEntryRow | None:
        return session.scalar(
            select(CreditLedgerEntryRow).where(
                CreditLedgerEntryRow.idempotency_key == idempotency_key
            )
        )

    @staticmethod
    def _add_ledger(
        session: Session,
        *,
        owner_id: str,
        entry_type: str,
        available_delta: int,
        reserved_delta: int,
        idempotency_key: str,
        reference_type: str | None,
        reference_id: str | None,
        metadata: dict | None = None,
    ) -> None:
        session.add(
            CreditLedgerEntryRow(
                id=str(uuid4()),
                owner_id=owner_id,
                entry_type=entry_type,
                available_delta=available_delta,
                reserved_delta=reserved_delta,
                idempotency_key=idempotency_key,
                reference_type=reference_type,
                reference_id=reference_id,
                entry_metadata=metadata or {},
            )
        )

    @staticmethod
    def _serialize_account(row: CreditAccountRow) -> dict:
        return {
            "owner_id": row.owner_id,
            "available_credits": row.available_credits,
            "reserved_credits": row.reserved_credits,
        }

    @staticmethod
    def _serialize_reservation(row: CreditReservationRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "amount": row.amount,
            "settled_amount": row.settled_amount,
            "released_amount": row.released_amount,
            "status": row.status,
            "idempotency_key": row.idempotency_key,
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }

    @staticmethod
    def _serialize_ledger(row: CreditLedgerEntryRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "entry_type": row.entry_type,
            "available_delta": row.available_delta,
            "reserved_delta": row.reserved_delta,
            "idempotency_key": row.idempotency_key,
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "metadata": row.entry_metadata,
            "created_at": row.created_at,
        }

    @staticmethod
    def _serialize_pack(row: CreditPackRow) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "credits": row.credits,
            "stripe_price_id": row.stripe_price_id,
            "active": row.active,
            "display_order": row.display_order,
        }
