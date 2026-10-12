import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import authenticate_request as get_current_user
from app.services.cache import get_revenue_summary

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:

    # FIX: never fall back to a shared "default_tenant" bucket.
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant associated with this user")

    if (month is None) != (year is None):
        raise HTTPException(status_code=400, detail="Provide both month and year, or neither")

    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, month, year)
    except Exception as exc:
        logger.error("Revenue lookup failed for %s (tenant %s): %s", property_id, tenant_id, exc)
        raise HTTPException(status_code=503, detail="Revenue data temporarily unavailable")

    return {
        "property_id": revenue_data["property_id"],
        # FIX: no float(). The amount is already a 2-decimal string computed with Decimal.
        "total_revenue": revenue_data["total"],
        "currency": revenue_data["currency"],
        "reservations_count": revenue_data["count"],
    }
