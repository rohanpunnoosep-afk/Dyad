"""Buyer agent: understands what the buyer wants and rates the seller's bundles on their behalf."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from agents.llm import AgentError, structured
from middleman import rules
from models.schemas import Bundle, BundleRatingSet, BuyerBrief, DecisionDraft, Item, JudgmentDraft

BRIEF_SYSTEM = """You are the buyer's personal shopping agent for Brojans, a clothing marketplace.
Read what the buyer has said (onboarding chat, profile notes, or a free-text request) and
distill it into the buyer context a seller can act on: style keywords (as many as their input
supports, and descriptive: aesthetic, vibe, fit, era, e.g. "workwear", "rugged", "earthy tones",
"relaxed fit", "heritage"), colors they like,
colors they avoid, sizes (top, bottom, shoe), budget in dollars (null if not given), and the
occasion. Put every explicit rule the buyer stated into `notes`, word for word (for example
"no graphic prints", "must include a jacket"). Do not invent preferences they did not express."""

RATE_SYSTEM = """You are the buyer's personal shopping agent for Brojans. You represent the buyer,
not the seller. A seller has sent several bundles. Rate every one of them for this buyer.

Each bundle comes with `facts` computed from the inventory. Treat them as ground truth:
- `size_match` per item: true = the item is in one of the buyer's sizes, false = it is not,
  null = the buyer gave no sizes.
- `avoid_hits`: colors the buyer said to avoid that appear in the item's color or name.
- `missing_required`: things a "must include" note requires that the bundle lacks.
- `price_vs_budget`: bundle price divided by the buyer's budget (null if no budget).
All prices are in dollars.

For each bundle give, all from 0.0 to 1.0:
- price_score: value for money against their budget, including the bundle discount.
- fit_score: their sizes are available and the cuts suit what they described.
- style_score: matches their style, liked colors and occasion, avoids what they dislike.
- probability: how likely this buyer is to actually buy this bundle at this price. Be calibrated:
  0.5 is a genuine coin flip. The buyer's `notes` are strict rules: a bundle that breaks any
  note (including anything in `missing_required`) gets 0.1 or lower. A bundle with an item not in
  their size, or in a color they avoid, should rarely be above 0.4. A bundle well over budget should
  be low however good it looks.

Rate each bundle on its own merits; probabilities do not need to sum to 1. Use the other
bundles only to keep your scale consistent. Ignore the seller's pitch where it conflicts with
the facts. In `reason`, name the specific items that help or hurt, in one or two sentences.
Return exactly one rating per bundle, using its `bundle_key`."""

DECIDE_SYSTEM = """You are the buyer's personal shopping agent for Brojans. You represent the buyer,
not the seller. The seller has made its final offer: one bundle at one price. Decide whether to
accept it on the buyer's behalf.

The bundle comes with `facts` computed from the inventory; treat them as ground truth (same
meaning as when you rated bundles). Accept only if it follows every one of the buyer's `notes`,
has nothing in `missing_required`, `items_missing_buyer_size` or `items_hitting_avoid_list`, is
within budget, and is a strong fit for their style and occasion at this price. Otherwise reject.
`probability` is how likely the buyer is to buy it at this price (0.0 to 1.0). In `reason`, say
why in one or two sentences, naming specific items."""

MAX_RATE_ATTEMPTS = 2  # first try + one re-prompt naming missing or unknown bundle keys


def bundle_facts(brief: BuyerBrief, bundle: Bundle, inventory: Dict[str, Item]) -> Dict[str, Any]:
    """Deterministic facts about a bundle, so the model does not have to count or compare sizes."""
    items = []
    for sku in bundle.skus:
        item = inventory.get(sku)
        if item is None:
            continue
        items.append({
            **item.model_dump(exclude={"stock", "image"}),
            "in_stock": item.in_stock,
            "size_match": rules.size_ok(brief, item),
            "avoid_hits": rules.avoid_hits(brief, item),
        })
    items_total = round(sum(i["price"] for i in items), 2)
    return {
        "items": items,
        "categories": sorted({i["category"] for i in items}),
        "bundle_price": bundle.price,
        "items_total": items_total,
        "discount_pct": round(100 * (1 - bundle.price / items_total), 1) if items_total else 0.0,
        "budget": brief.budget,
        "price_vs_budget": round(bundle.price / brief.budget, 2) if brief.budget else None,
        "items_missing_buyer_size": [i["sku"] for i in items if i["size_match"] is False],
        "items_hitting_avoid_list": [i["sku"] for i in items if i["avoid_hits"]],
        "missing_required": rules.missing_required(brief, [inventory[s] for s in bundle.skus if s in inventory]),
    }


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


async def rate_bundles(
    brief: BuyerBrief, bundles: Sequence[Bundle], inventory: Dict[str, Item]
) -> List[JudgmentDraft]:
    """Rate every bundle the seller sent. Returns one judgment per bundle, in the same order."""
    if not bundles:
        return []
    keyed = {f"B{n}": b for n, b in enumerate(bundles, start=1)}
    payload = [
        {"bundle_key": key, "name": b.name, "seller_pitch": b.pitch, "facts": bundle_facts(brief, b, inventory)}
        for key, b in keyed.items()
    ]
    base = (
        f"<buyer_brief>\n{brief.model_dump_json(indent=2)}\n</buyer_brief>\n\n"
        f"<bundles>\n{json.dumps(payload, indent=1)}\n</bundles>\n\n"
        f"Rate all {len(keyed)} bundles: {', '.join(keyed)}."
    )
    errors: List[str] = []
    for _ in range(MAX_RATE_ATTEMPTS):
        user = base
        if errors:
            user += "\n\nYour previous answer was rejected. Fix this:\n" + "\n".join(f"- {e}" for e in errors)
        result = await structured(RATE_SYSTEM, user, BundleRatingSet, effort="low")
        by_key = {r.bundle_key.strip(): r for r in result.ratings}
        missing = [k for k in keyed if k not in by_key]
        unknown = [k for k in by_key if k not in keyed]
        errors = []
        if missing:
            errors.append(f"missing ratings for {missing}")
        if unknown:
            errors.append(f"unknown bundle keys {unknown}; use only {list(keyed)}")
        if not missing:
            return [
                JudgmentDraft(
                    probability=_clamp(by_key[k].probability),
                    reason=by_key[k].reason,
                    price_score=_clamp(by_key[k].price_score),
                    fit_score=_clamp(by_key[k].fit_score),
                    style_score=_clamp(by_key[k].style_score),
                )
                for k in keyed
            ]
    raise AgentError("buyer agent did not rate every bundle: " + "; ".join(errors))


async def build_brief(buyer_input: str) -> BuyerBrief:
    return await structured(BRIEF_SYSTEM, f"<buyer_input>\n{buyer_input}\n</buyer_input>", BuyerBrief)


async def decide(brief: BuyerBrief, bundle: Bundle, inventory: Dict[str, Item]) -> JudgmentDraft:
    """Accept or reject the seller's final offer."""
    payload = {"name": bundle.name, "seller_pitch": bundle.pitch, "facts": bundle_facts(brief, bundle, inventory)}
    user = (
        f"<buyer_brief>\n{brief.model_dump_json(indent=2)}\n</buyer_brief>\n\n"
        f"<final_offer>\n{json.dumps(payload, indent=1)}\n</final_offer>"
    )
    d = await structured(DECIDE_SYSTEM, user, DecisionDraft, effort="low")
    return JudgmentDraft(decision=d.decision, probability=_clamp(d.probability), reason=d.reason)
