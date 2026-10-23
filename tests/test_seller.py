import asyncio
import json
import re

from agents import seller
from middleman import analysis
from middleman.heat import compute_item_heat
from models.schemas import (
    AnalysisDraft,
    Bundle,
    BundleSet,
    ItemCheckDraft,
    ItemStyle,
    Judgment,
    SignalDraft,
)
from tests.conftest import BRIEF, COLD_ITEM, HOT_ITEM, ROUND_BUNDLES, STYLES, FakeAgents, draft


def _inventory_skus(prompt: str):
    block = re.search(r"<inventory>\n(.*?)\n</inventory>", prompt, re.S).group(1)
    return {row["sku"] for row in json.loads(block)}


def test_eligible_inventory_applies_stock_size_and_avoid_rules(items):
    skus = {i.sku for i in seller.eligible_inventory(BRIEF, items)}
    assert {"JKT-01-BR-M", "PNT-01-OL-32", "BOT-01-BR-10", "BNE-01-RU-OS"} <= skus
    assert "JKT-01-BR-L" not in skus                 # not the buyer's size
    assert "JKT-04-NY-M" not in skus                 # neon yellow, avoided
    assert "HOD-01-NG-M" not in skus                 # neon green, avoided
    assert not any(s.startswith("BOT-01-BR-11") for s in skus)  # wrong size and out of stock


def test_propose_prompt_has_only_eligible_items_and_hard_requirements(items, monkeypatch):
    seen = {}

    async def fake_structured(system, user, model, effort=None):
        seen["system"], seen["user"] = system, user
        return BundleSet(bundles=[])

    monkeypatch.setattr(seller, "structured", fake_structured)
    asyncio.run(seller.propose_bundles(BRIEF, items, 5, errors=["bundle 1: no jacket"]))
    assert _inventory_skus(seen["user"]) == {i.sku for i in seller.eligible_inventory(BRIEF, items)}
    assert "Propose exactly 5 bundles" in seen["user"]
    assert "must include a jacket" in seen["user"] and "at most 400" in seen["user"]
    assert "bundle 1: no jacket" in seen["user"]
    assert '"image"' not in seen["user"]
    assert "notes" in seen["system"]


def _round(items):
    inv = {i.sku: i for i in items}
    fake = FakeAgents(items)
    bundles = [Bundle(id=f"id{n}", negotiation_id="n", round=1, **draft(k, v, inv).model_dump())
               for n, (k, v) in enumerate(ROUND_BUNDLES.items(), start=1)]
    drafts = asyncio.run(fake.rate_bundles(BRIEF, bundles, inv))
    judgments = [Judgment(bundle_id=b.id, negotiation_id="n", round=1, **d.model_dump())
                 for b, d in zip(bundles, drafts)]
    keyed = {f"B{n}": b for n, b in enumerate(bundles, start=1)}
    return inv, keyed, judgments, compute_item_heat(bundles, judgments)


def test_attribute_averages_count_each_value_once_per_bundle(items):
    inv, keyed, judgments, _ = _round(items)
    avgs = analysis.attribute_averages(list(keyed.values()), judgments, inv)
    # brown: workwear (0.9) and rugged (0.9); rugged has two brown items but counts once
    assert avgs["color"]["brown"] == 0.9
    # jacket is in every bundle: (0.9 + 0.1 + 0.5 + 0.5 + 0.9) / 5
    assert avgs["category"]["jacket"] == 0.58
    assert "style" not in avgs
    assert analysis.low_bundle_keys(keyed, judgments) == ["B2"]


def test_finalize_cross_checks_items_against_collective_and_drops_made_up_data(items):
    inv, keyed, judgments, heat = _round(items)
    round_skus = {s for b in keyed.values() for s in b.skus}
    draft_ = AnalysisDraft(
        item_styles=[ItemStyle(sku=s, style=STYLES[s].upper()) for s in round_skus] + [ItemStyle(sku="X", style="y")],
        item_checks=[
            ItemCheckDraft(bundle_key="B2", sku=COLD_ITEM, verdict="hurts", dimension="style", note="formal"),
            ItemCheckDraft(bundle_key="B2", sku="TRS-01-GR-32", verdict="hurts", dimension="style", note="formal"),
            ItemCheckDraft(bundle_key="B2", sku="JKT-03-NV-M", verdict="hurts", dimension="color", note="navy"),
            ItemCheckDraft(bundle_key="B2", sku=COLD_ITEM, verdict="hurts", dimension="style", note="dup"),
            ItemCheckDraft(bundle_key="B1", sku=HOT_ITEM, verdict="hurts", dimension="color", note="B1 is not low"),
            ItemCheckDraft(bundle_key="B2", sku="NOT-IN-BUNDLE", verdict="hurts", dimension="style", note="?"),
        ],
        works=[SignalDraft(type="color", value="Brown")],
        fails=[
            SignalDraft(type="style", value="Formal"),
            SignalDraft(type="color", value="navy"),
            SignalDraft(type="color", value="olive"),   # blamed by nobody
            SignalDraft(type="price", value="too expensive"),
        ],
        keep_skus=[HOT_ITEM, COLD_ITEM, "MADE-UP"],
        drop_skus=["TRS-01-GR-32", "MADE-UP"],
        main_issue="style",
    )
    result = analysis.finalize(draft_, 1, keyed, judgments, inv, heat)

    assert result.avg == 0.58
    assert result.subscore_avgs == {"price": 0.6, "fit": 0.7, "style": 0.58}
    assert result.attribute_avgs["style"]["formal"] == 0.1
    assert [(c.bundle_id, c.sku) for c in result.item_checks] == [
        ("id2", COLD_ITEM), ("id2", "TRS-01-GR-32"), ("id2", "JKT-03-NV-M")]

    works = {(s.type, s.value): s for s in result.works}
    assert works[("color", "brown")].avg_prob == 0.9 and not works[("color", "brown")].confirmed
    fails = {(s.type, s.value): s for s in result.fails}
    assert fails[("style", "formal")].votes == 2 and fails[("style", "formal")].confirmed
    assert fails[("color", "navy")].votes == 1 and fails[("color", "navy")].confirmed
    assert fails[("color", "olive")].votes == 0 and not fails[("color", "olive")].confirmed
    # no per-item price value: falls back to the price sub-score (0.6, not low) and no hurts votes
    assert fails[("price", "too expensive")].avg_prob is None and not fails[("price", "too expensive")].confirmed

    cold = {h.sku for h in heat if h.label.value == "cold"}
    assert set(result.drop_skus) == {"TRS-01-GR-32"} | cold
    assert result.keep_skus == [HOT_ITEM]  # COLD_ITEM is dropped, MADE-UP is not in the round


def test_final_prompt_excludes_dropped_skus(items, monkeypatch):
    inv, keyed, judgments, heat = _round(items)
    fake = FakeAgents(items)
    draft_ = asyncio.run(fake.analyze_round(BRIEF, keyed, judgments, inv, heat, {}, ["B2"]))
    result = analysis.finalize(draft_, 1, keyed, judgments, inv, heat)
    seen = {}

    async def fake_structured(system, user, model, effort=None):
        seen["user"] = user
        return BundleSet(bundles=[])

    monkeypatch.setattr(seller, "structured", fake_structured)
    asyncio.run(seller.final_bundle(BRIEF, items, keyed, judgments, result, None))
    offered = _inventory_skus(seen["user"])
    assert HOT_ITEM in offered and not offered & set(result.drop_skus)
    assert "<rated_bundles>" in seen["user"] and '"main_issue": "style"' in seen["user"]
    assert "Propose exactly 1 bundle" in seen["user"]
