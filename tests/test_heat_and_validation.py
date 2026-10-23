import pytest

from middleman import pricing
from middleman.heat import compute_item_heat
from middleman.validation import ValidationFailed, validate_bundles
from models.schemas import Bundle, BundleDraft, HeatLabel, Judgment
from tests.conftest import BRIEF


def _b(id_, skus):
    return Bundle(id=id_, negotiation_id="n", round=1, name=id_, skus=skus, price=100, pitch="")


def _j(bundle_id, p):
    return Judgment(bundle_id=bundle_id, negotiation_id="n", round=1, probability=p, reason="")


def test_heat_is_mean_probability_of_containing_bundles():
    bundles = [_b("a", ["x", "y"]), _b("b", ["y", "z"]), _b("c", ["w"])]
    judgments = [_j("a", 0.9), _j("b", 0.1), _j("c", 0.5)]
    heat = {h.sku: h for h in compute_item_heat(bundles, judgments)}
    assert heat["x"].score == pytest.approx(0.9) and heat["x"].label == HeatLabel.HOT
    assert heat["y"].score == pytest.approx(0.5) and heat["y"].label == HeatLabel.NEUTRAL
    assert heat["y"].bundle_count == 2
    assert heat["z"].score == pytest.approx(0.1) and heat["z"].label == HeatLabel.COLD
    assert [h.sku for h in compute_item_heat(bundles, judgments)][0] == "x"


def test_heat_ignores_unjudged_bundles():
    assert compute_item_heat([_b("a", ["x"])], []) == []


def _draft(inv, skus, price=None, name="d", terms=("standard", "2 weeks", 30)):
    """A draft priced by the pricing policy unless `price` overrides it."""
    shipping, window, refund = terms
    q = pricing.quote([inv[s] for s in skus if s in inv], shipping, window, refund)
    return BundleDraft(name=name, skus=skus, price=q.price if price is None else price, pitch="",
                       shipping=shipping, delivery_days=q.delivery_days, return_window=window, refund_pct=refund)


JACKET_TEE = ["JKT-01-BR-M", "TEE-01-OL-M"]  # total 124


def test_validation_accepts_good_bundle(items):
    inv = {i.sku: i for i in items}
    validate_bundles([_draft(inv, JACKET_TEE)], inv, 1, 1, brief=BRIEF)


def test_same_items_with_different_terms_are_different_bundles(items):
    inv = {i.sku: i for i in items}
    validate_bundles([_draft(inv, JACKET_TEE), _draft(inv, JACKET_TEE, terms=("express", "6 months", 100))],
                     inv, 2, 2, brief=BRIEF)


@pytest.mark.parametrize(
    "specs, banned, fragment",
    [
        ([(["JKT-01-BR-M", "nope"], 80)], (), "unknown SKUs"),
        ([(["JKT-01-BR-M", "JKT-01-BR-M"], None)], (), "repeats a SKU"),
        ([(JACKET_TEE, 10)], (), "does not match the pricing policy"),
        ([(JACKET_TEE, 200)], (), "does not match the pricing policy"),
        ([(JACKET_TEE, None)], ("TEE-01-OL-M",), "rejected"),
        ([(["JKT-01-BR-M"], None)], (), "needs 2-5"),
        ([(["BOT-01-BR-11", "JKT-01-BR-M"], None)], (), "out-of-stock"),
        ([(JACKET_TEE, None), (list(reversed(JACKET_TEE)), None)], (), "same items and terms as bundle 1"),
        ([], (), "expected 1-2 bundles"),
    ],
)
def test_validation_rejects(items, specs, banned, fragment):
    inv = {i.sku: i for i in items}
    drafts = [_draft(inv, skus, price) for skus, price in specs]
    with pytest.raises(ValidationFailed) as exc:
        validate_bundles(drafts, inv, 1, 2, banned)
    assert fragment in str(exc.value)


def test_validation_rejects_wrong_delivery_days(items):
    inv = {i.sku: i for i in items}
    d = _draft(inv, JACKET_TEE, terms=("priority", "2 weeks", 30)).model_copy(update={"delivery_days": 9})
    with pytest.raises(ValidationFailed, match="delivery_days 9 should be 1 for priority"):
        validate_bundles([d], inv, 1, 1)


@pytest.mark.parametrize(
    "skus, fragment",
    [
        (["JKT-01-BR-L", "TEE-01-OL-M"], "not in the buyer's sizes"),
        (["JKT-04-NY-M", "TEE-01-OL-M"], "colors the buyer avoids"),
        (["TEE-01-OL-M", "PNT-01-OL-32"], "must include a jacket"),
        (["JKT-02-OL-M", "BLZ-01-NV-M", "BOT-01-BR-10"], "over the buyer's budget"),
    ],
)
def test_validation_enforces_buyer_rules(items, skus, fragment):
    inv = {i.sku: i for i in items}
    validate_bundles([_draft(inv, skus)], inv, 1, 1)  # fine without the brief
    with pytest.raises(ValidationFailed) as exc:
        validate_bundles([_draft(inv, skus)], inv, 1, 1, brief=BRIEF)
    assert fragment in str(exc.value)
