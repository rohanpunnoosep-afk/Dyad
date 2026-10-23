"""The seller's pricing policy, applied in code so every bundle price is reproducible.

price = items_total x (1 - margin discount + shipping + rush + return guarantee)

- Margin discount: the more aggregate gross margin the bundle's pieces carry, the more the seller
  can give away: (margin - 40) / 2 percent, capped at MAX_MARGIN_DISCOUNT_PCT.
- Shipping: standard ships in the slowest item's average delivery time; express and priority are
  faster and cost more.
- Rush: a buyer who wants their clothes within a few days pays a premium on top of shipping.
- Return guarantee: the longer the window and the larger the refund, the higher the premium.

frontend/src/pricing.ts mirrors this module; keep the two in step.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

from pydantic import BaseModel

from models.schemas import Item

MARGIN_FLOOR_PCT = 40.0         # no discount on bundles at or below this aggregate margin
MARGIN_DISCOUNT_SHARE = 0.5     # percent of discount per percent of margin above the floor
MAX_MARGIN_DISCOUNT_PCT = 25.0

# Shipping tier -> surcharge % of the items total. Delivery days per tier: see delivery_days().
SHIPPING: Dict[str, float] = {"standard": 0.0, "express": 6.0, "priority": 12.0}

# Return guarantee premium = refund share x window rate.
RETURN_WINDOWS: Dict[str, float] = {"2 weeks": 4.0, "2 months": 8.0, "6 months": 14.0}
REFUND_PCTS = (30, 75, 100)

# Buyer wants delivery within at most N days -> rush premium %.
RUSH: Sequence[tuple] = ((2, 6.0), (5, 3.0))


class Quote(BaseModel):
    items_total: float
    margin_pct: float               # revenue-weighted gross margin of the pieces (seller-only)
    margin_discount_pct: float
    shipping_pct: float
    rush_pct: float
    returns_pct: float
    delivery_days: int
    price: float


def aggregate_margin(items: Sequence[Item]) -> float:
    total = sum(i.price for i in items)
    return round(sum(i.price * i.margin_pct for i in items) / total, 1) if total else 0.0


def margin_discount(margin_pct: float, cap: float = MAX_MARGIN_DISCOUNT_PCT) -> float:
    return round(min(cap, max(0.0, (margin_pct - MARGIN_FLOOR_PCT) * MARGIN_DISCOUNT_SHARE)), 1)


def standard_days(items: Sequence[Item]) -> int:
    return max((i.delivery_days for i in items), default=0)


def delivery_days(items: Sequence[Item], shipping: str) -> int:
    base = standard_days(items)
    if shipping == "express":
        return max(2, math.ceil(base / 2))
    if shipping == "priority":
        return max(1, math.ceil(base / 4))
    return base


def rush_premium(wanted_within_days: Optional[int]) -> float:
    if wanted_within_days is None:
        return 0.0
    for limit, pct in RUSH:
        if wanted_within_days <= limit:
            return pct
    return 0.0


def returns_premium(return_window: str, refund_pct: int) -> float:
    return round(RETURN_WINDOWS[return_window] * refund_pct / 100, 2)


def quote(
    items: Sequence[Item],
    shipping: str,
    return_window: str,
    refund_pct: int,
    wanted_within_days: Optional[int] = None,
) -> Quote:
    total = round(sum(i.price for i in items), 2)
    margin = aggregate_margin(items)
    disc = margin_discount(margin)
    ship = SHIPPING[shipping]
    rush = rush_premium(wanted_within_days)
    ret = returns_premium(return_window, refund_pct)
    price = math.floor(total * (1 + (ship + rush + ret - disc) / 100) + 0.5)
    return Quote(items_total=total, margin_pct=margin, margin_discount_pct=disc, shipping_pct=ship,
                 rush_pct=rush, returns_pct=ret, delivery_days=delivery_days(items, shipping), price=price)
