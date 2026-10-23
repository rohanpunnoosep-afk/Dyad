"""Seller agent: builds bundles from inventory, analyzes the buyer's ratings, makes the final offer.

Mirrors the buyer agent: anything that can be computed (eligibility, totals, averages) is done in
code and handed to the model as fact; the model does the merchandising judgment.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from agents.llm import structured
from middleman import rules
from middleman.validation import MAX_ITEMS, MAX_PRICE_RATIO, MIN_ITEMS, MIN_PRICE_RATIO
from models.schemas import (
    AnalysisDraft,
    Bundle,
    BundleDraft,
    BundleSet,
    BuyerBrief,
    Item,
    ItemHeat,
    Judgment,
    RoundAnalysis,
)

SYSTEM = f"""You are the seller's merchandising agent for Brojans, a clothing marketplace.
You build clothing bundles from the seller's inventory for one specific buyer and price them.

STRICT RULES (the middle man rejects any bundle that breaks one):
- Use only SKUs from the inventory you are given. Every one is in stock, in the buyer's sizes and
  free of colors they avoid, so do not reach for anything else.
- Follow every one of the buyer's `notes` exactly. They are the buyer's own rules.
- {MIN_ITEMS}-{MAX_ITEMS} items per bundle, never the same SKU twice in a bundle.
- Price in dollars, between {int(MIN_PRICE_RATIO * 100)}% and {int(MAX_PRICE_RATIO * 100)}% of the sum
  of the bundle's item prices, and never above the buyer's budget. A modest bundle discount helps
  conversion; do not give away margin unnecessarily.

`pitch` is one or two sentences to the buyer about that bundle."""

ANALYST_SYSTEM = """You are the seller's analyst for Brojans. The buyer's agent has rated the bundles
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
        "(style, colors, categories, price point) so the buyer's ratings tell us what works."
        f"{_requirements(brief)}{_retry_block(errors)}"
    )
    return (await structured(SYSTEM, user, BundleSet)).bundles


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
        "drop_skus. Choose the price most likely to close without giving away margin. In `pitch`, say "
        "why this bundle, citing the ratings."
        f"{_requirements(brief)}{_retry_block(errors)}"
    )
    return (await structured(SYSTEM, user, BundleSet)).bundles
