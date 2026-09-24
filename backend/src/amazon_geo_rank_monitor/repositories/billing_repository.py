from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.domain.errors import InsufficientCreditsError

from .models import (
    CreditAccountRow,
    CreditLedgerEntryRow,
    CreditReservationRow,
)


class BillingRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def ensure_account(self, owner_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(CreditAccountRow, owner_id)
            if row is None:
                row = CreditAccountRow(owner_id=owner_id, balance=0, reserved=0)
                session.add(row)
        return self.get_balance(owner_id)

    def get_balance(self, owner_id: str) -> dict:
        with self._sessions() as session:
            row = session.get(CreditAccountRow, owner_id)
            if row is None:
                return {"balance": 0, "reserved": 0, "available": 0}
            return self._serialize_account(row)

    def grant(
        self,
        *,
        owner_id: str,
        credits: int,
        idempotency_key: str,
        entry_type: str = "purchase",
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> dict:
        if credits <= 0:
            raise ValueError("credits must be positive")
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(CreditLedgerEntryRow).where(
                    CreditLedgerEntryRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                account = session.get(CreditAccountRow, owner_id)
                return self._serialize_account(account)

            account = self._account_for_update(session, owner_id)
            account.balance += credits
            account.updated_at = datetime.now(UTC)
            session.add(
                CreditLedgerEntryRow(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    entry_type=entry_type,
                    delta_credits=credits,
                    balance_after=account.balance,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    idempotency_key=idempotency_key,
                )
            )
            return self._serialize_account(account)

    def reserve(
        self,
        *,
        owner_id: str,
        credits: int,
        idempotency_key: str,
        reference_type: str,
        reference_id: str,
    ) -> dict:
        if credits <= 0:
            raise ValueError("credits must be positive")
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(CreditReservationRow).where(
                    CreditReservationRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return self._serialize_reservation(existing)

            account = self._account_for_update(session, owner_id)
            available = account.balance - account.reserved
            if available < credits:
                raise InsufficientCreditsError(
                    f"insufficient credits: need {credits}, available {available}"
                )
            account.reserved += credits
            account.updated_at = datetime.now(UTC)
            reservation = CreditReservationRow(
                id=str(uuid4()),
                owner_id=owner_id,
                amount=credits,
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key,
                status="reserved",
            )
            session.add(reservation)
            session.add(
                CreditLedgerEntryRow(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    entry_type="reservation",
                    delta_credits=0,
                    balance_after=account.balance,
                    reservation_id=reservation.id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    idempotency_key=f"{idempotency_key}:reserve",
                )
            )
            return self._serialize_reservation(reservation)

    def settle(self, reservation_id: str, *, credits_used: int) -> dict:
        with self._sessions.begin() as session:
            reservation = session.scalar(
                select(CreditReservationRow)
                .where(CreditReservationRow.id == reservation_id)
                .with_for_update()
            )
            if reservation is None:
                raise KeyError(f"credit reservation not found: {reservation_id}")
            if reservation.status != "reserved":
                return self._serialize_reservation(reservation)
            if credits_used < 0 or credits_used > reservation.amount:
                raise ValueError("credits_used must be between 0 and reserved amount")

            account = self._account_for_update(session, reservation.owner_id)
            account.reserved -= reservation.amount
            account.balance -= credits_used
            account.updated_at = datetime.now(UTC)
            released = reservation.amount - credits_used
            reservation.settled_amount = credits_used
            reservation.released_amount = released
            reservation.status = "settled" if credits_used else "released"
            reservation.completed_at = datetime.now(UTC)

            if credits_used:
                session.add(
                    CreditLedgerEntryRow(
                        id=str(uuid4()),
                        owner_id=reservation.owner_id,
                        entry_type="settlement",
                        delta_credits=-credits_used,
                        balance_after=account.balance,
                        reservation_id=reservation.id,
                        reference_type=reservation.reference_type,
                        reference_id=reservation.reference_id,
                        idempotency_key=f"reservation:{reservation.id}:settlement",
                    )
                )
            if released:
                session.add(
                    CreditLedgerEntryRow(
                        id=str(uuid4()),
                        owner_id=reservation.owner_id,
                        entry_type="release",
                        delta_credits=0,
                        balance_after=account.balance,
                        reservation_id=reservation.id,
                        reference_type=reservation.reference_type,
                        reference_id=reservation.reference_id,
                        idempotency_key=f"reservation:{reservation.id}:release",
                    )
                )
            return self._serialize_reservation(reservation)

    def release(self, reservation_id: str) -> dict:
        return self.settle(reservation_id, credits_used=0)

    def list_ledger(self, *, owner_id: str, limit: int = 100) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(CreditLedgerEntryRow)
                .where(CreditLedgerEntryRow.owner_id == owner_id)
                .order_by(CreditLedgerEntryRow.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "entry_type": row.entry_type,
                    "delta_credits": row.delta_credits,
                    "balance_after": row.balance_after,
                    "reservation_id": row.reservation_id,
                    "reference_type": row.reference_type,
                    "reference_id": row.reference_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def get_reservation(self, reservation_id: str) -> dict:
        with self._sessions() as session:
            row = session.get(CreditReservationRow, reservation_id)
            if row is None:
                raise KeyError(f"credit reservation not found: {reservation_id}")
            return self._serialize_reservation(row)

    @staticmethod
    def _account_for_update(session, owner_id: str) -> CreditAccountRow:
        account = session.scalar(
            select(CreditAccountRow)
            .where(CreditAccountRow.owner_id == owner_id)
            .with_for_update()
        )
        if account is None:
            account = CreditAccountRow(owner_id=owner_id, balance=0, reserved=0)
            session.add(account)
            session.flush()
        return account

    @staticmethod
    def _serialize_account(row: CreditAccountRow | None) -> dict:
        if row is None:
            return {"balance": 0, "reserved": 0, "available": 0}
        return {
            "balance": row.balance,
            "reserved": row.reserved,
            "available": row.balance - row.reserved,
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
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "idempotency_key": row.idempotency_key,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }
