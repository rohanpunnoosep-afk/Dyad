"""Guardrails on agent output before the middle man accepts it (json_formats.md section 4)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from middleman import rules
from models.schemas import BuyerBrief, BundleDraft, Item

# Bundle price must land within this band of the sum of its item prices.
MIN_PRICE_RATIO = 0.6
MAX_PRICE_RATIO = 1.05
MIN_ITEMS = 2
MAX_ITEMS = 5


class ValidationFailed(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_bundles(
    drafts: List[BundleDraft],
    inventory: Dict[str, Item],
    min_count: int,
    max_count: int,
    banned_skus: Optional[Iterable[str]] = None,
    brief: Optional[BuyerBrief] = None,
) -> None:
    """Raise ValidationFailed listing every problem with a seller's bundle set.

    With a brief, the buyer's hard rules (sizes, colors_avoid, budget, "must include" notes)
    are enforced too.
    """
    errors: List[str] = []
    banned = set(banned_skus or ())

    if not (min_count <= len(drafts) <= max_count):
        errors.append(f"expected {min_count}-{max_count} bundles, got {len(drafts)}")

    seen = {}
    for i, d in enumerate(drafts):
        label = f"bundle {i + 1} ({d.name!r})"
        if not (MIN_ITEMS <= len(d.skus) <= MAX_ITEMS):
            errors.append(f"{label}: has {len(d.skus)} items, needs {MIN_ITEMS}-{MAX_ITEMS}")
            if not d.skus:
                continue
        if len(set(d.skus)) != len(d.skus):
            errors.append(f"{label}: repeats a SKU")
        key = frozenset(d.skus)
        if key in seen:
            errors.append(f"{label}: same items as bundle {seen[key] + 1}")
        seen.setdefault(key, i)
        unknown = [x for x in d.skus if x not in inventory]
        if unknown:
            errors.append(f"{label}: unknown SKUs {unknown}")
            continue
        items = [inventory[x] for x in d.skus]
        out_of_stock = [i.sku for i in items if not i.in_stock]
        if out_of_stock:
            errors.append(f"{label}: out-of-stock SKUs {out_of_stock}")
        used_banned = [x for x in d.skus if x in banned]
        if used_banned:
            errors.append(f"{label}: includes SKUs the buyer rejected {used_banned}")
        total = rules.items_total(items)
        lo, hi = round(total * MIN_PRICE_RATIO, 2), round(total * MAX_PRICE_RATIO, 2)
        if not (lo <= d.price <= hi):
            errors.append(f"{label}: price {d.price} outside allowed range {lo}-{hi} (items total {total})")
        if brief is None:
            continue
        wrong_size = [i.sku for i in items if rules.size_ok(brief, i) is False]
        if wrong_size:
            errors.append(f"{label}: SKUs not in the buyer's sizes {wrong_size}")
        avoided = [i.sku for i in items if rules.avoid_hits(brief, i)]
        if avoided:
            errors.append(f"{label}: SKUs in colors the buyer avoids {avoided}")
        if brief.budget is not None and d.price > brief.budget:
            errors.append(f"{label}: price {d.price} is over the buyer's budget {brief.budget}")
        for thing in rules.missing_required(brief, items):
            errors.append(f"{label}: no {thing} (breaks note 'must include a {thing}')")

    if errors:
        raise ValidationFailed(errors)


def clamp_probability(p: float) -> float:
    return max(0.0, min(1.0, float(p)))
