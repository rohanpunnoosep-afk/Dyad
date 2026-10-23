"""Guardrails on agent output before the middle man accepts it (json_formats.md section 4)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from middleman import pricing, rules
from models.schemas import BuyerBrief, BundleDraft, Item

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
    are enforced too. Prices must match the seller's pricing policy (middleman/pricing.py).
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
        # The same pieces may be offered again with different shipping or return terms.
        key = (frozenset(d.skus), d.shipping, d.return_window, d.refund_pct)
        if key in seen:
            errors.append(f"{label}: same items and terms as bundle {seen[key] + 1}")
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
        q = pricing.quote(items, d.shipping, d.return_window, d.refund_pct,
                          brief.delivery_days if brief else None)
        if abs(d.price - q.price) > 0.005:
            errors.append(f"{label}: price {d.price} does not match the pricing policy quote {q.price}")
        if d.delivery_days != q.delivery_days:
            errors.append(f"{label}: delivery_days {d.delivery_days} should be {q.delivery_days} for {d.shipping}")
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
