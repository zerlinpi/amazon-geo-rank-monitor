from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import CheckoutCreate
from amazon_geo_rank_monitor.billing.errors import WebhookSignatureError

router = APIRouter(prefix="/api/v1", tags=["billing"])


def _billing_repository(request: Request):
    repository = get_services(request).billing_repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="billing is not configured",
        )
    return repository


def _stripe_billing(request: Request):
    service = get_services(request).stripe_billing
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe billing is not configured",
        )
    return service


@router.get("/credits")
def get_credits(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    return _billing_repository(request).get_account(owner_id)


@router.get("/credits/ledger")
def get_credit_ledger(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    return _billing_repository(request).list_ledger(owner_id=owner_id)


@router.get("/billing/packs")
def list_credit_packs(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    del owner_id
    packs = _billing_repository(request).list_credit_packs(active_only=True)
    return [
        {
            "id": pack["id"],
            "name": pack["name"],
            "credits": pack["credits"],
            "active": pack["active"],
            "display_order": pack["display_order"],
        }
        for pack in packs
    ]


@router.post("/billing/checkout")
def create_checkout(
    body: CheckoutCreate,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    try:
        return _stripe_billing(request).create_checkout(
            owner_id=owner_id,
            credit_pack_id=body.credit_pack_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/billing/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[
        str | None,
        Header(alias="Stripe-Signature"),
    ] = None,
):
    if not stripe_signature:
        raise HTTPException(
            status_code=400,
            detail="Stripe-Signature header is required",
        )
    payload = await request.body()
    try:
        return _stripe_billing(request).handle_webhook(
            payload=payload,
            signature=stripe_signature,
        )
    except (WebhookSignatureError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="invalid Stripe webhook") from exc
