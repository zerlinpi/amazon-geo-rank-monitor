from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.api.schemas import CheckoutCreate
from amazon_geo_rank_monitor.billing.rate_card import RateCard

router = APIRouter(prefix="/api/v1", tags=["billing"])


@router.get("/billing/status")
def billing_status(
    request: Request,
    owner_id: str = Depends(require_scope("billing:read")),
):
    del owner_id
    services = get_services(request)
    free = services.billing_mode == "free"
    rates = services.rate_card or RateCard()
    return {
        "mode": services.billing_mode,
        "managed_credit_cost": 0 if free else rates.managed_serp,
        "strict_credit_cost": 0 if free else rates.browser_verified_serp,
        "checkout_available": bool(
            not free and services.stripe_billing is not None
            and services.billing_repository is not None
            and services.billing_repository.list_credit_packs()
        ),
    }


@router.get("/credits")
def credit_balance(
    request: Request,
    owner_id: str = Depends(require_scope("billing:read")),
):
    billing = get_services(request).billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.get_balance(owner_id)


@router.get("/credits/ledger")
def credit_ledger(
    request: Request,
    owner_id: str = Depends(require_scope("billing:read")),
    limit: int = 100,
):
    billing = get_services(request).billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.list_ledger(owner_id=owner_id, limit=min(max(limit, 1), 500))


@router.get("/billing/packs")
def credit_packs(
    request: Request,
    owner_id: str = Depends(require_scope("billing:read")),
):
    del owner_id
    services = get_services(request)
    if services.billing_mode == "free" or services.stripe_billing is None:
        return []
    billing = services.billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.list_credit_packs()


@router.post("/billing/checkout", status_code=201)
def create_checkout(
    body: CheckoutCreate,
    request: Request,
    owner_id: str = Depends(require_scope("billing:write")),
):
    services = get_services(request)
    if services.billing_mode == "free":
        raise HTTPException(status_code=409, detail="Free mode is active; checkout is disabled")
    stripe_billing = services.stripe_billing
    if stripe_billing is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe billing is not configured",
        )
    try:
        return stripe_billing.create_checkout(
            owner_id=owner_id,
            credit_pack_id=body.credit_pack_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="credit pack not found") from exc


@router.post("/billing/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[
        str | None,
        Header(alias="Stripe-Signature"),
    ] = None,
):
    stripe_billing = get_services(request).stripe_billing
    if stripe_billing is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe billing is not configured",
        )
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Stripe-Signature required")
    payload = await request.body()
    try:
        return stripe_billing.process_webhook(
            payload=payload,
            signature=stripe_signature,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid Stripe webhook") from exc
