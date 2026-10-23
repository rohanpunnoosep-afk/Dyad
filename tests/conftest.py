import os
import sys
from typing import Dict, List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repo import MemoryRepo, _MemoryStore, load_seed_items  # noqa: E402
from middleman.orchestrator import Agents  # noqa: E402
from models.schemas import (  # noqa: E402
    AnalysisDraft,
    Bundle,
    BundleDraft,
    BuyerBrief,
    ItemCheckDraft,
    ItemStyle,
    JudgmentDraft,
    SignalDraft,
    Sizes,
)

HOT_ITEM = "JKT-01-BR-M"   # buyer loves this
COLD_ITEM = "SHT-01-BL-M"  # buyer hates this

BRIEF = BuyerBrief(
    style=["workwear", "minimal"],
    colors_liked=["brown", "olive"],
    colors_avoid=["neon"],
    sizes=Sizes(top="M", bottom="32", shoe="10"),
    budget=400,
    occasion="weekend casual",
    notes=["no graphic prints", "must include a jacket"],
)

ROUND_BUNDLES = {
    "workwear": [HOT_ITEM, "TEE-01-OL-M", "PNT-01-OL-32"],
    "formal": ["JKT-03-NV-M", COLD_ITEM, "TRS-01-GR-32"],
    "minimal": ["JKT-02-OL-M", "TEE-02-WH-M", "JNS-01-IN-32"],
    "lounge": ["JKT-02-OL-M", "HOD-02-HG-M", "JOG-01-CH-32"],
    "rugged": [HOT_ITEM, "JNS-01-IN-32", "BOT-01-BR-10"],
}
FINAL_SKUS = [HOT_ITEM, "TEE-01-OL-M", "PNT-01-OL-32", "BOT-01-BR-10"]

STYLES = {HOT_ITEM: "workwear", "TEE-01-OL-M": "workwear", "PNT-01-OL-32": "workwear",
          "BOT-01-BR-10": "workwear", "JKT-03-NV-M": "sporty", COLD_ITEM: "formal",
          "TRS-01-GR-32": "formal", "JKT-02-OL-M": "workwear", "TEE-02-WH-M": "minimal",
          "JNS-01-IN-32": "minimal", "HOD-02-HG-M": "loungewear", "JOG-01-CH-32": "loungewear"}


def draft(name: str, skus: List[str], inventory: Dict, ratio: float = 0.9) -> BundleDraft:
    total = sum(inventory[s].price for s in skus)
    return BundleDraft(name=name, skus=skus, price=round(total * ratio, 2), pitch=f"pitch for {name}")


class FakeAgents(Agents):
    """Deterministic agents. `fail_on` makes a method raise once; `bad_first` returns invalid output once."""

    def __init__(self, inventory, fail_on: Optional[str] = None, bad_first: Optional[str] = None):
        self.inv = {i.sku: i for i in inventory}
        self.fail_on, self.bad_first = fail_on, bad_first
        self.calls: Dict[str, int] = {}
        self.seen: Dict[str, object] = {}

    def _tick(self, name: str) -> int:
        self.calls[name] = self.calls.get(name, 0) + 1
        if self.fail_on == name:
            self.fail_on = None
            raise RuntimeError(f"boom in {name}")
        return self.calls[name]

    async def build_brief(self, buyer_input):
        self._tick("build_brief")
        return BRIEF

    async def rate_bundles(self, brief, bundles: List[Bundle], inventory):
        self._tick("rate_bundles")
        out = []
        for bundle in bundles:
            p = 0.5 + (0.4 if HOT_ITEM in bundle.skus else 0) - (0.4 if COLD_ITEM in bundle.skus else 0)
            out.append(JudgmentDraft(probability=p, reason=f"judged {bundle.name}",
                                     price_score=0.6, fit_score=0.7, style_score=p))
        return out

    async def decide(self, brief, bundle: Bundle, inventory):
        self._tick("decide")
        return JudgmentDraft(decision="accept", probability=0.88, reason=f"accept {bundle.name}")

    async def propose_bundles(self, brief, inventory, count, errors=None):
        n = self._tick("propose_bundles")
        self.seen.setdefault("propose_errors", []).append(errors)
        if self.bad_first == "propose_bundles" and n == 1:
            # no jacket in the first bundle, and the rest are fine
            bad = [draft("no-jacket", ["TEE-01-OL-M", "PNT-01-OL-32"], self.inv)]
            return bad + [draft(k, v, self.inv) for k, v in list(ROUND_BUNDLES.items())[1:]]
        return [draft(k, v, self.inv) for k, v in ROUND_BUNDLES.items()][:count]

    async def analyze_round(self, brief, keyed, judgments, inventory, heat, attribute_avgs, check_keys):
        self._tick("analyze_round")
        self.seen["check_keys"] = list(check_keys)
        self.seen["attribute_avgs"] = attribute_avgs
        round_skus = {s for b in keyed.values() for s in b.skus}
        checks = [
            ItemCheckDraft(bundle_key=k, sku=s, verdict="hurts" if STYLES[s] in ("formal", "sporty") else "neutral",
                           dimension="style" if STYLES[s] in ("formal", "sporty") else "none", note=STYLES[s])
            for k in check_keys for s in keyed[k].skus
        ]
        return AnalysisDraft(
            item_styles=[ItemStyle(sku=s, style=STYLES[s]) for s in round_skus],
            item_checks=checks,
            works=[SignalDraft(type="color", value="brown"), SignalDraft(type="style", value="workwear")],
            fails=[SignalDraft(type="style", value="formal"), SignalDraft(type="style", value="sporty")],
            keep_skus=[HOT_ITEM, "TEE-01-OL-M", "PNT-01-OL-32", "BOT-01-BR-10"],
            drop_skus=[COLD_ITEM, "TRS-01-GR-32"],
            main_issue="style",
        )

    async def final_bundle(self, brief, inventory, keyed, judgments, analysis, errors=None):
        n = self._tick("final_bundle")
        self.seen.setdefault("final_errors", []).append(errors)
        if self.bad_first == "final_bundle" and n == 1:
            # ignores the analysis and keeps a dropped item
            return [draft("bad-final", [HOT_ITEM, COLD_ITEM], self.inv)]
        return [draft("final", FINAL_SKUS, self.inv)]


@pytest.fixture
def items():
    return load_seed_items()


@pytest.fixture
def repo(items) -> MemoryRepo:
    r = MemoryRepo(_MemoryStore())
    r.seed_items(items)
    return r
