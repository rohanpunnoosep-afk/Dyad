import asyncio

import pytest

from agents import buyer
from agents.llm import AgentError
from models.schemas import Bundle, BundleRating, BundleRatingSet
from tests.conftest import BRIEF


def _bundle(id_, skus, price):
    return Bundle(id=id_, negotiation_id="n", round=1, name=id_, skus=skus, price=price, pitch="trust me")


def _rating(key, p):
    return BundleRating(bundle_key=key, price_score=0.5, fit_score=0.5, style_score=0.5, probability=p, reason=key)


def test_bundle_facts_flags_sizes_avoid_hits_required_and_price(items):
    inv = {i.sku: i for i in items}
    # TEE-01-OL-M fits; JKT-04-NY-M is neon (avoid list); PNT-01-OL-34 is not the buyer's 32; BNE is one size
    skus = ["TEE-01-OL-M", "JKT-04-NY-M", "PNT-01-OL-34", "BNE-01-RU-OS"]
    facts = buyer.bundle_facts(BRIEF, _bundle("b", skus, 200), inv)
    by_sku = {i["sku"]: i for i in facts["items"]}
    assert by_sku["TEE-01-OL-M"]["size_match"] is True
    assert by_sku["PNT-01-OL-34"]["size_match"] is False
    assert by_sku["BNE-01-RU-OS"]["size_match"] is True
    assert by_sku["JKT-04-NY-M"]["avoid_hits"] == ["neon"]
    assert "image" not in by_sku["TEE-01-OL-M"] and "stock" not in by_sku["TEE-01-OL-M"]
    assert facts["items_missing_buyer_size"] == ["PNT-01-OL-34"]
    assert facts["items_hitting_avoid_list"] == ["JKT-04-NY-M"]
    assert facts["missing_required"] == []  # the windbreaker is a jacket
    assert facts["items_total"] == sum(inv[s].price for s in skus)
    assert facts["price_vs_budget"] == round(200 / BRIEF.budget, 2)

    no_jacket = buyer.bundle_facts(BRIEF, _bundle("c", ["TEE-01-OL-M", "PNT-01-OL-32"], 100), inv)
    assert no_jacket["missing_required"] == ["jacket"]


def test_rate_bundles_maps_keys_back_in_order_and_clamps(items, monkeypatch):
    inv = {i.sku: i for i in items}
    bundles = [_bundle("x", ["JKT-01-BR-M"], 80), _bundle("y", ["SHT-01-BL-M"], 60)]

    async def fake_structured(system, user, model, effort=None):
        assert '"bundle_key": "B1"' in user and '"bundle_key": "B2"' in user
        # out of order, and one probability out of range
        return BundleRatingSet(ratings=[_rating("B2", 1.7), _rating("B1", 0.8)])

    monkeypatch.setattr(buyer, "structured", fake_structured)
    out = asyncio.run(buyer.rate_bundles(BRIEF, bundles, inv))
    assert [j.reason for j in out] == ["B1", "B2"]
    assert [j.probability for j in out] == [0.8, 1.0]
    assert out[0].style_score == 0.5


def test_rate_bundles_reprompts_on_missing_ratings_then_gives_up(items, monkeypatch):
    inv = {i.sku: i for i in items}
    bundles = [_bundle("x", ["JKT-01-BR-M"], 80), _bundle("y", ["SHT-01-BL-M"], 60)]
    prompts = []

    async def fake_structured(system, user, model, effort=None):
        prompts.append(user)
        return BundleRatingSet(ratings=[_rating("B1", 0.5), _rating("B9", 0.5)])

    monkeypatch.setattr(buyer, "structured", fake_structured)
    with pytest.raises(AgentError, match="did not rate every bundle"):
        asyncio.run(buyer.rate_bundles(BRIEF, bundles, inv))
    assert len(prompts) == buyer.MAX_RATE_ATTEMPTS
    assert "missing ratings for ['B2']" in prompts[1] and "B9" in prompts[1]
