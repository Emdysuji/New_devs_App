import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def to_money(value: Any) -> Decimal:
    """
    FIX: money stays Decimal end to end and is rounded once, half-up, to cents.
    The DB stores NUMERIC(10,3), so sub-cent values like 333.333 are expected.
    """
    return Decimal(str(value if value is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def month_bounds_utc(month: int, year: int, tz_name: str) -> Tuple[datetime, datetime]:
    """
    FIX: "March" must mean March in the PROPERTY's timezone, not UTC.
    Example: a Paris booking checking in 2024-02-29 23:30 UTC is 2024-03-01 00:30
    local time, so it belongs to March for that property.
    """
    tz = ZoneInfo(tz_name)
    start_local = datetime(year, month, 1, tzinfo=tz)
    if month < 12:
        end_local = datetime(year, month + 1, 1, tzinfo=tz)
    else:
        end_local = datetime(year + 1, 1, 1, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def _open_session():
    if not db_pool.session_factory:
        await db_pool.initialize()
    if not db_pool.session_factory:
        raise RuntimeError("Database pool not available")
    return db_pool.session_factory()


async def calculate_monthly_revenue(
    property_id: str, tenant_id: str, month: int, year: int
) -> Dict[str, Any]:
    """
    Calculates revenue for one calendar month in the property's own timezone.
    """
    async with await _open_session() as session:
        tz_row = (
            await session.execute(
                text("SELECT timezone FROM properties WHERE id = :pid AND tenant_id = :tid"),
                {"pid": property_id, "tid": tenant_id},
            )
        ).fetchone()
        tz_name = tz_row.timezone if tz_row else "UTC"
        start_utc, end_utc = month_bounds_utc(month, year, tz_name)

        row = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(total_amount), 0) AS total,
                           COUNT(*) AS reservation_count,
                           COALESCE(MAX(currency), 'USD') AS currency
                    FROM reservations
                    WHERE property_id = :pid
                      AND tenant_id = :tid
                      AND check_in_date >= :start
                      AND check_in_date < :end
                    """
                ),
                {"pid": property_id, "tid": tenant_id, "start": start_utc, "end": end_utc},
            )
        ).fetchone()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_money(row.total)),
        "currency": row.currency,
        "count": row.reservation_count,
    }


async def calculate_total_revenue(
    property_id: str,
    tenant_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aggregates revenue from the database, always scoped to the tenant.
    FIX: no more silent fallback to hardcoded mock data. If the database is
    unavailable the error surfaces instead of showing wrong numbers.
    """
    if month and year:
        return await calculate_monthly_revenue(property_id, tenant_id, month, year)

    async with await _open_session() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(total_amount), 0) AS total,
                           COUNT(*) AS reservation_count,
                           COALESCE(MAX(currency), 'USD') AS currency
                    FROM reservations
                    WHERE property_id = :pid AND tenant_id = :tid
                    """
                ),
                {"pid": property_id, "tid": tenant_id},
            )
        ).fetchone()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_money(row.total)),
        "currency": row.currency,
        "count": row.reservation_count,
    }
