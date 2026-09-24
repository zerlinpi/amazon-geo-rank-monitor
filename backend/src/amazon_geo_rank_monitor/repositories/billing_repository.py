from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.domain.errors import InsufficientCreditsError

from .models import (
    CreditAccountRow,
    CreditLedgerEntryRow,
    CreditPackRow,
    CreditReservationRow,
    PaymentRow,
    WebhookEventRow,
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
                if existing.owner_id != owner_id:
                    raise ValueError("idempotency key belongs to another tenant")
                if existing.delta_credits != credits:
                    raise ValueError("idempotency key was used with different credits")
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
                if existing.owner_id != owner_id:
                    raise ValueError("idempotency key belongs to another tenant")
                if (
                    existing.amount != credits
                    or existing.reference_type != reference_type
                    or existing.reference_id != reference_id
                ):
                    raise ValueError(
                        "idempotency key was used with different reservation parameters"
                    )
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

    def release_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        with self._sessions() as session:
            reservation_id = session.scalar(
                select(CreditReservationRow.id).where(
                    CreditReservationRow.idempotency_key == idempotency_key
                )
            )
        if reservation_id is None:
            return None
        return self.release(reservation_id)

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


    def upsert_credit_pack(
        self,
        *,
        pack_id: str,
        name: str,
        credits: int,
        amount_minor: int,
        currency: str = "usd",
        active: bool = True,
    ) -> dict:
        if credits <= 0 or amount_minor <= 0:
            raise ValueError("pack credits and amount_minor must be positive")
        with self._sessions.begin() as session:
            row = session.get(CreditPackRow, pack_id)
            if row is None:
                row = CreditPackRow(id=pack_id)
                session.add(row)
            row.name = name
            row.credits = credits
            row.amount_minor = amount_minor
            row.currency = currency.lower()
            row.active = active
        return self.get_credit_pack(pack_id, active_only=False)

    def list_credit_packs(self, *, active_only: bool = True) -> list[dict]:
        with self._sessions() as session:
            statement = select(CreditPackRow).order_by(CreditPackRow.credits)
            if active_only:
                statement = statement.where(CreditPackRow.active.is_(True))
            rows = session.scalars(statement).all()
            return [self._serialize_pack(row) for row in rows]

    def get_credit_pack(self, pack_id: str, *, active_only: bool = True) -> dict:
        with self._sessions() as session:
            row = session.get(CreditPackRow, pack_id)
            if row is None or (active_only and not row.active):
                raise KeyError(f"credit pack not found: {pack_id}")
            return self._serialize_pack(row)

    def create_payment(self, *, owner_id: str, credit_pack_id: str) -> dict:
        pack = self.get_credit_pack(credit_pack_id)
        payment_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                PaymentRow(
                    id=payment_id,
                    owner_id=owner_id,
                    credit_pack_id=pack["id"],
                    provider="stripe",
                    provider_session_id=None,
                    amount_minor=pack["amount_minor"],
                    currency=pack["currency"],
                    credits=pack["credits"],
                    status="pending",
                )
            )
        return self.get_payment(payment_id, owner_id=owner_id)

    def attach_payment_session(self, payment_id: str, *, session_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(PaymentRow, payment_id)
            if row is None:
                raise KeyError(f"payment not found: {payment_id}")
            if row.provider_session_id and row.provider_session_id != session_id:
                raise ValueError("payment already has a different checkout session")
            row.provider_session_id = session_id
            owner_id = row.owner_id
        return self.get_payment(payment_id, owner_id=owner_id)

    def get_payment(self, payment_id: str, *, owner_id: str | None = None) -> dict:
        with self._sessions() as session:
            row = session.get(PaymentRow, payment_id)
            if row is None or (owner_id is not None and row.owner_id != owner_id):
                raise KeyError(f"payment not found: {payment_id}")
            return self._serialize_payment(row)

    def record_webhook_event(
        self,
        *,
        provider_event_id: str,
        event_type: str,
        payload_hash: str,
    ) -> bool:
        with self._sessions.begin() as session:
            if session.get(WebhookEventRow, provider_event_id) is not None:
                return False
            session.add(
                WebhookEventRow(
                    provider_event_id=provider_event_id,
                    event_type=event_type,
                    payload_hash=payload_hash,
                )
            )
            return True

    def apply_paid_checkout(
        self,
        *,
        provider_event_id: str,
        event_type: str,
        payload_hash: str,
        payment_id: str,
        session_id: str,
        payment_intent_id: str | None,
    ) -> dict:
        with self._sessions.begin() as session:
            if session.get(WebhookEventRow, provider_event_id) is not None:
                row = session.get(PaymentRow, payment_id)
                if row is None:
                    raise KeyError(f"payment not found: {payment_id}")
                return self._serialize_payment(row)

            payment = session.scalar(
                select(PaymentRow)
                .where(PaymentRow.id == payment_id)
                .with_for_update()
            )
            if payment is None:
                raise KeyError(f"payment not found: {payment_id}")
            if payment.provider_session_id not in {None, session_id}:
                raise ValueError("checkout session does not match payment")
            payment.provider_session_id = session_id

            if payment.status != "paid":
                account = self._account_for_update(session, payment.owner_id)
                account.balance += payment.credits
                account.updated_at = datetime.now(UTC)
                payment.status = "paid"
                payment.provider_payment_intent_id = payment_intent_id
                payment.paid_at = datetime.now(UTC)
                session.add(
                    CreditLedgerEntryRow(
                        id=str(uuid4()),
                        owner_id=payment.owner_id,
                        entry_type="purchase",
                        delta_credits=payment.credits,
                        balance_after=account.balance,
                        reference_type="stripe_checkout",
                        reference_id=session_id,
                        idempotency_key=f"stripe_session:{session_id}:credits",
                    )
                )

            session.add(
                WebhookEventRow(
                    provider_event_id=provider_event_id,
                    event_type=event_type,
                    payload_hash=payload_hash,
                )
            )
            return self._serialize_payment(payment)

    @staticmethod
    def _serialize_pack(row: CreditPackRow) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "credits": row.credits,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "active": row.active,
        }

    @staticmethod
    def _serialize_payment(row: PaymentRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "credit_pack_id": row.credit_pack_id,
            "provider": row.provider,
            "provider_session_id": row.provider_session_id,
            "provider_payment_intent_id": row.provider_payment_intent_id,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "credits": row.credits,
            "status": row.status,
            "created_at": row.created_at,
            "paid_at": row.paid_at,
        }

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
