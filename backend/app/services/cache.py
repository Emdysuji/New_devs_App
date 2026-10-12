import json
import logging
import os
from typing import Any, Dict, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def build_cache_key(
    tenant_id: str,
    property_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> str:
    """
    FIX: the key used to be f"revenue:{property_id}". Property IDs repeat across
    tenants (prop-001 exists for both Sunset and Ocean), so one client could be
    served another client's cached revenue. The tenant must be part of the key.
    """
    period = f"{year}-{month:02d}" if month and year else "all"
    return f"revenue:{tenant_id}:{property_id}:{period}"


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    cache_key = build_cache_key(tenant_id, property_id, month, year)

    # Try to get from cache (a Redis outage must not take the dashboard down)
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.warning("Redis read failed for %s: %s", cache_key, exc)

    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue

    result = await calculate_total_revenue(property_id, tenant_id, month, year)

    # Cache the result for 5 minutes
    try:
        await redis_client.setex(cache_key, 300, json.dumps(result))
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s", cache_key, exc)

    return result
