from fastapi import APIRouter, Depends, Request

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/status")
def notification_status(
    request: Request,
    owner_id: str = Depends(require_scope("monitors:read")),
):
    """Expose configuration presence only; this does not probe SMTP connectivity."""
    return {"email": {"configured": get_services(request).email_delivery_configured}}
