from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import CheckoutCreate

router = APIRouter(prefix="/api/v1", tags=["billing"])


@router.get("/credits")
def credit_balance(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    billing = get_services(request).billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.get_balance(owner_id)


@router.get("/credits/ledger")
def credit_ledger(
    request: Request,
    owner_id: str = Depends(current_tenant),
    limit: int = 100,
):
    billing = get_services(request).billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.list_ledger(owner_id=owner_id, limit=min(max(limit, 1), 500))


@router.get("/billing/packs")
def credit_packs(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    del owner_id
    billing = get_services(request).billing_repository
    if billing is None:
        raise HTTPException(status_code=503, detail="billing is unavailable")
    return billing.list_credit_packs()


@router.post("/billing/checkout", status_code=201)
def create_checkout(
    body: CheckoutCreate,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    stripe_billing = get_services(request).stripe_billing
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
