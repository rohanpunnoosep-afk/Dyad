"""The numbers behind the seller's round analysis (json_formats.md section 6).

The seller agent looks at every item of every low-rated bundle and says why it hurts. This
module computes the collective view (the mean buy probability of bundles containing each
attribute value, plus the buyer's sub-score averages) and cross-checks the two: a failing
attribute is `confirmed` only when item-level verdicts blamed it AND its collective average is
below the round average.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence

from middleman.rules import norm
from models.schemas import (
    AnalysisDraft,
    Bundle,
    HeatLabel,
    Item,
    ItemCheck,
    ItemHeat,
    Judgment,
    RoundAnalysis,
    Signal,
    SignalDraft,
)

LOW_PROBABILITY = 0.5  # bundles rated below this get an item-by-item check
ITEM_ATTRIBUTES = ("category", "color", "material", "size")
# Dimensions with no per-item attribute fall back to the matching buyer sub-score.
SUBSCORE_FOR = {"price": "price", "fit": "fit", "size": "fit"}


def _mean(xs: Sequence[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def round_average(judgments: Sequence[Judgment]) -> float:
    return _mean([j.probability for j in judgments])


def subscore_averages(judgments: Sequence[Judgment]) -> Dict[str, float]:
    out = {}
    for name in ("price", "fit", "style"):
        vals = [getattr(j, f"{name}_score") for j in judgments if getattr(j, f"{name}_score") is not None]
        if vals:
            out[name] = _mean(vals)
    return out


def low_bundle_keys(keyed: Mapping[str, Bundle], judgments: Sequence[Judgment]) -> List[str]:
    prob = {j.bundle_id: j.probability for j in judgments}
    return [k for k, b in keyed.items() if b.id in prob and prob[b.id] < LOW_PROBABILITY]


def attribute_averages(
    bundles: Sequence[Bundle],
    judgments: Sequence[Judgment],
    inventory: Mapping[str, Item],
    styles: Optional[Mapping[str, str]] = None,
) -> Dict[str, Dict[str, float]]:
    """For each attribute value, the mean probability of the bundles that contain it.

    Same rule as item heat: a value counts once per bundle, however many items carry it.
    `styles` (SKU -> style label from the seller's analyst) adds a "style" dimension.
    """
    prob = {j.bundle_id: j.probability for j in judgments}
    dims = ITEM_ATTRIBUTES + (("style",) if styles else ())
    probs: Dict[str, Dict[str, List[float]]] = {d: defaultdict(list) for d in dims}
    for b in bundles:
        if b.id not in prob:
            continue
        items = [inventory[s] for s in b.skus if s in inventory]
        for d in dims:
            if d == "style":
                values = {styles[i.sku] for i in items if i.sku in styles}
            else:
                values = {norm(getattr(i, d)) for i in items}
            for v in values:
                probs[d][v].append(prob[b.id])
    return {
        d: dict(sorted(((v, _mean(ps)) for v, ps in by_value.items()), key=lambda kv: -kv[1]))
        for d, by_value in probs.items()
        if by_value
    }


def _dedupe(xs: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(xs))


def finalize(
    draft: AnalysisDraft,
    round_: int,
    keyed: Mapping[str, Bundle],
    judgments: Sequence[Judgment],
    inventory: Mapping[str, Item],
    heat: Sequence[ItemHeat],
) -> RoundAnalysis:
    """Merge the seller agent's analysis with the computed numbers, dropping anything it made up."""
    bundles = list(keyed.values())
    round_skus = {s for b in bundles for s in b.skus}
    styles = {s.sku: norm(s.style) for s in draft.item_styles if s.sku in round_skus and s.style.strip()}
    attr_avgs = attribute_averages(bundles, judgments, inventory, styles)
    avg = round_average(judgments)
    subs = subscore_averages(judgments)

    low = set(low_bundle_keys(keyed, judgments))
    checks: List[ItemCheck] = []
    seen = set()
    for c in draft.item_checks:
        key = c.bundle_key.strip()
        if key not in low or c.sku not in keyed[key].skus or (key, c.sku) in seen:
            continue
        seen.add((key, c.sku))
        checks.append(ItemCheck(bundle_id=keyed[key].id, sku=c.sku, verdict=c.verdict,
                                dimension=c.dimension, note=c.note))

    def value_of(sku: str, dim: str) -> Optional[str]:
        if dim == "style":
            return styles.get(sku)
        if dim in ITEM_ATTRIBUTES and sku in inventory:
            return norm(getattr(inventory[sku], dim))
        return None

    def signal(s: SignalDraft, failing: bool) -> Signal:
        value = norm(s.value)
        avg_prob = attr_avgs.get(s.type, {}).get(value)
        votes = 0
        if failing:
            for c in checks:
                if c.verdict != "hurts" or c.dimension != s.type:
                    continue
                item_value = value_of(c.sku, s.type)
                if item_value is None or item_value == value:
                    votes += 1
        if avg_prob is not None:
            below = avg_prob < avg
        elif SUBSCORE_FOR.get(s.type) in subs:
            below = subs[SUBSCORE_FOR[s.type]] < LOW_PROBABILITY
        else:
            below = False
        return Signal(type=s.type, value=value, avg_prob=avg_prob, votes=votes,
                      confirmed=failing and votes > 0 and below)

    def signals(drafts: Sequence[SignalDraft], failing: bool) -> List[Signal]:
        out, keys = [], set()
        for s in drafts:
            k = (s.type, norm(s.value))
            if k[1] and k not in keys:
                keys.add(k)
                out.append(signal(s, failing))
        return out

    cold = [h.sku for h in heat if h.label == HeatLabel.COLD]
    drop = _dedupe([s for s in draft.drop_skus if s in round_skus] + cold)
    keep = _dedupe([s for s in draft.keep_skus if s in round_skus and s not in drop])

    return RoundAnalysis(
        round=round_,
        avg=avg,
        subscore_avgs=subs,
        attribute_avgs=attr_avgs,
        item_checks=checks,
        works=signals(draft.works, failing=False),
        fails=signals(draft.fails, failing=True),
        keep_skus=keep,
        drop_skus=drop,
        main_issue=draft.main_issue,
    )
