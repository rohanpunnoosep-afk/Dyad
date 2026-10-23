"""Seller agent: builds bundles from inventory, analyzes the buyer's ratings, makes the final offer.

Mirrors the buyer agent: anything that can be computed (eligibility, totals, averages) is done in
code and handed to the model as fact; the model does the merchandising judgment.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from agents.llm import structured
from middleman import pricing, rules
from middleman.validation import MAX_ITEMS, MIN_ITEMS
from models.schemas import (
    AnalysisDraft,
    Bundle,
    BundleDraft,
    BundleProposal,
    BuyerBrief,
    Item,
    ItemHeat,
    Judgment,
    ProposalSet,
    RoundAnalysis,
)


def _pct(x: float) -> str:
    return f"{x:g}%"


_RETURN_TABLE = "\n".join(
    f"    {w}: " + ", ".join(f"{r}% back = +{_pct(pricing.returns_premium(w, r))}" for r in pricing.REFUND_PCTS)
    for w in pricing.RETURN_WINDOWS
)

SYSTEM = f"""You are the seller's merchandising agent for Dyad, a clothing marketplace.
You build clothing bundles from the seller's inventory for one specific buyer. Each bundle is a
set of pieces plus the terms they come with: a shipping speed and a return guarantee.

STRICT RULES (the middle man rejects any bundle that breaks one):
- Use only SKUs from the inventory you are given. Every one is in stock, in the buyer's sizes and
  free of colors they avoid, so do not reach for anything else.
- Follow every one of the buyer's `notes` exactly. They are the buyer's own rules.
- {MIN_ITEMS}-{MAX_ITEMS} items per bundle, never the same SKU twice in a bundle.
- The bundle price must not be above the buyer's budget.

PRICING POLICY. You do not set prices; code computes them from the pieces and terms you choose:
  price = items total x (1 - margin discount + shipping + rush + return guarantee)
- Margin discount: each inventory row has `margin_pct` (gross margin) and `delivery_days`
  (average days to deliver with standard shipping). The discount is (aggregate margin - {pricing.MARGIN_FLOOR_PCT:g})
  x {pricing.MARGIN_DISCOUNT_SHARE:g}, capped at {_pct(pricing.MAX_MARGIN_DISCOUNT_PCT)}, where aggregate margin is the price-weighted
  margin of the pieces. More high-margin pieces = a bigger discount for the buyer. `margin_pct`
  is confidential: never mention it in a name or pitch.
- Shipping: "standard" (+0%) arrives in the slowest piece's delivery_days; "express"
  (+{_pct(pricing.SHIPPING['express'])}) in half that (at least 2 days); "priority" (+{_pct(pricing.SHIPPING['priority'])}) in a quarter (at least 1 day).
- Rush: a buyer who wants delivery within {pricing.RUSH[0][0]} days pays +{_pct(pricing.RUSH[0][1])}, within {pricing.RUSH[1][0]} days +{_pct(pricing.RUSH[1][1])}.
- Return guarantee: the longer the window and the more money back, the more it costs:
{_RETURN_TABLE}

When the buyer wants their clothes fast (`delivery_days`, `needed_by`), prefer pieces with low
delivery_days and the cheapest shipping speed that still arrives in time. Weigh how much the
buyer cares about returns (`returns_note`, `return_window`) when choosing guarantees. Take the
buyer's `additional_notes` seriously as preferences.

`pitch` is one or two sentences to the buyer about that bundle and its terms."""

ANALYST_SYSTEM = """You are the seller's analyst for Dyad. The buyer's agent has rated the bundles
you sent. Work out what works and what doesn't so the final offer sells.

You get the buyer context (its `style` keywords describe what they want), each bundle with its
items, its rating (buy probability, price/fit/style sub-scores and reason), each SKU's heat
(mean probability of the bundles containing it) and the mean probability of the bundles
containing each category, color, material and size value. Treat these numbers as ground truth.

1. item_styles: for EVERY SKU in the round, a short style label (e.g. "workwear", "formal",
   "sporty", "loungewear", "streetwear"). Prefer the buyer's own style keywords where they fit,
   and use the same label for items of the same style.
2. item_checks: for EVERY item of every bundle listed in `check_bundles` (rated below 0.5), say
   whether it hurts, is neutral, or helps that bundle, and the dimension responsible
   (category / style / color / material / size / price / fit, or none). Use the buyer's reason.
3. works / fails: the attribute values that pull ratings up / down. `value` must be a value that
   appears in the data (a category, color, material, size, or one of your style labels).
4. keep_skus: SKUs the final bundle should be built around. drop_skus: SKUs that hurt.
5. main_issue: the single dimension most responsible for low ratings, or "none".
Only call something a problem if the item-level evidence and the averages agree."""


def eligible_inventory(brief: BuyerBrief, inventory: Sequence[Item]) -> List[Item]:
    """In-stock SKUs in the buyer's sizes and not in colors they avoid."""
    return [i for i in inventory if rules.eligible(brief, i)]


def _item_row(item: Item) -> Dict[str, Any]:
    return item.model_dump(exclude={"image"})


def price_proposals(
    brief: BuyerBrief, proposals: Sequence[BundleProposal], inventory: Sequence[Item]
) -> List[BundleDraft]:
    """Apply the pricing policy. Unknown SKUs leave the price at 0 for validation to reject."""
    by_sku = {i.sku: i for i in inventory}
    out = []
    for p in proposals:
        items = [by_sku[s] for s in p.skus if s in by_sku]
        price, days = 0.0, 0
        if items and len(items) == len(p.skus):
            q = pricing.quote(items, p.shipping, p.return_window, p.refund_pct, brief.delivery_days)
            price, days = q.price, q.delivery_days
        out.append(BundleDraft(name=p.name, skus=p.skus, price=price, pitch=p.pitch, shipping=p.shipping,
                               delivery_days=days, return_window=p.return_window, refund_pct=p.refund_pct))
    return out


def _context_block(brief: BuyerBrief) -> str:
    return f"<buyer_context>\n{brief.model_dump_json(indent=2)}\n</buyer_context>"


def _inventory_block(items: Sequence[Item]) -> str:
    return f"<inventory>\n{json.dumps([_item_row(i) for i in items], indent=1)}\n</inventory>"


def _requirements(brief: BuyerBrief) -> str:
    lines = []
    for thing in rules.required_things(brief):
        lines.append(f"- Every bundle must include a {thing} (buyer note).")
    if brief.budget is not None:
        lines.append(f"- Every bundle price must be at most {brief.budget}.")
    if brief.delivery_days is not None:
        lines.append(f"- The buyer wants delivery within {brief.delivery_days} days; choose pieces and shipping "
                     "that arrive in time.")
    return ("\n\nHard requirements for this buyer:\n" + "\n".join(lines)) if lines else ""


def _retry_block(errors: Optional[List[str]]) -> str:
    if not errors:
        return ""
    joined = "\n".join(f"- {e}" for e in errors)
    return f"\n\nYour previous answer was rejected for these reasons. Fix all of them:\n{joined}"


def _rated_bundles(
    keyed: Mapping[str, Bundle], judgments: Sequence[Judgment], inventory: Mapping[str, Item]
) -> List[Dict[str, Any]]:
    by_bundle = {j.bundle_id: j for j in judgments}
    out = []
    for key, b in keyed.items():
        items = [inventory[s] for s in b.skus if s in inventory]
        j = by_bundle.get(b.id)
        out.append({
            "bundle_key": key,
            "name": b.name,
            "items": [_item_row(i) for i in items],
            "items_total": rules.items_total(items),
            "price": b.price,
            "shipping": b.shipping,
            "delivery_days": b.delivery_days,
            "return_window": b.return_window,
            "refund_pct": b.refund_pct,
            "rating": None if j is None else {
                "probability": j.probability,
                "price_score": j.price_score,
                "fit_score": j.fit_score,
                "style_score": j.style_score,
                "reason": j.reason,
            },
        })
    return out


async def propose_bundles(
    brief: BuyerBrief, inventory: Sequence[Item], count: int, errors: Optional[List[str]] = None
) -> List[BundleDraft]:
    user = (
        f"{_context_block(brief)}\n\n{_inventory_block(eligible_inventory(brief, inventory))}\n\n"
        f"Propose exactly {count} bundles for this buyer. Make them clearly different from each other "
        "(style, colors, categories, price point, shipping speed and return guarantee) so the buyer's "
        "ratings tell us what works. Across the set, use every return window (2 weeks, 2 months, 6 months) "
        "and every refund level (30%, 75%, 100%). The same pieces may appear more than once with "
        "different terms, but no two bundles may have the same pieces and terms."
        f"{_requirements(brief)}{_retry_block(errors)}"
    )
    proposals = (await structured(SYSTEM, user, ProposalSet)).bundles
    return price_proposals(brief, proposals, inventory)


async def analyze_round(
    brief: BuyerBrief,
    keyed: Mapping[str, Bundle],
    judgments: Sequence[Judgment],
    inventory: Mapping[str, Item],
    heat: Sequence[ItemHeat],
    attribute_avgs: Mapping[str, Mapping[str, float]],
    check_keys: Sequence[str],
) -> AnalysisDraft:
    payload = {
        "round_avg": round(sum(j.probability for j in judgments) / len(judgments), 3) if judgments else None,
        "bundles": _rated_bundles(keyed, judgments, inventory),
        "check_bundles": list(check_keys),
        "sku_heat": [h.model_dump(mode="json") for h in heat],
        "attribute_avgs": attribute_avgs,
    }
    user = f"{_context_block(brief)}\n\n<round>\n{json.dumps(payload, indent=1)}\n</round>"
    return await structured(ANALYST_SYSTEM, user, AnalysisDraft, effort="low")


async def final_bundle(
    brief: BuyerBrief,
    inventory: Sequence[Item],
    keyed: Mapping[str, Bundle],
    judgments: Sequence[Judgment],
    analysis: RoundAnalysis,
    errors: Optional[List[str]] = None,
) -> List[BundleDraft]:
    """Returns a list so the middle man's validation can enforce that it is exactly one bundle."""
    by_sku = {i.sku: i for i in inventory}
    banned = set(analysis.drop_skus)
    allowed = [i for i in eligible_inventory(brief, inventory) if i.sku not in banned]
    user = (
        f"{_context_block(brief)}\n\n{_inventory_block(allowed)}\n\n"
        f"<rated_bundles>\n{json.dumps(_rated_bundles(keyed, judgments, by_sku), indent=1)}\n</rated_bundles>\n\n"
        f"<analysis>\n{analysis.model_dump_json(indent=1, exclude={'item_checks'})}\n</analysis>\n\n"
        "This is the final offer. Propose exactly 1 bundle: the one most likely to sell. Start from the "
        "highest-rated bundle, build around keep_skus and what works, fix the main issue, and never use "
        "drop_skus. Choose the shipping speed and return guarantee most likely to close, using how the "
        "buyer rated the terms; favor high-margin pieces where they fit so the bundle discount is larger. "
        "In `pitch`, say why this bundle and these terms, citing the ratings."
        f"{_requirements(brief)}{_retry_block(errors)}"
    )
    proposals = (await structured(SYSTEM, user, ProposalSet)).bundles
    return price_proposals(brief, proposals, inventory)
