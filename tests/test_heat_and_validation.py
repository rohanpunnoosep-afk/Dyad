import pytest

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


def _draft(skus, price, name="d"):
    return BundleDraft(name=name, skus=skus, price=price, pitch="")


JACKET_TEE = ["JKT-01-BR-M", "TEE-01-OL-M"]  # total 124


def test_validation_accepts_good_bundle(items):
    inv = {i.sku: i for i in items}
    validate_bundles([_draft(JACKET_TEE, 110)], inv, 1, 1, brief=BRIEF)


@pytest.mark.parametrize(
    "drafts, banned, fragment",
    [
        ([_draft(["JKT-01-BR-M", "nope"], 80)], (), "unknown SKUs"),
        ([_draft(["JKT-01-BR-M", "JKT-01-BR-M"], 160)], (), "repeats a SKU"),
        ([_draft(JACKET_TEE, 10)], (), "outside allowed range"),
        ([_draft(JACKET_TEE, 200)], (), "outside allowed range"),
        ([_draft(JACKET_TEE, 110)], ("TEE-01-OL-M",), "rejected"),
        ([_draft(["JKT-01-BR-M"], 80)], (), "needs 2-5"),
        ([_draft(["BOT-01-BR-11", "JKT-01-BR-M"], 200)], (), "out-of-stock"),
        ([_draft(JACKET_TEE, 110), _draft(list(reversed(JACKET_TEE)), 110)], (), "same items as bundle 1"),
        ([], (), "expected 1-2 bundles"),
    ],
)
def test_validation_rejects(items, drafts, banned, fragment):
    inv = {i.sku: i for i in items}
    with pytest.raises(ValidationFailed) as exc:
        validate_bundles(drafts, inv, 1, 2, banned)
    assert fragment in str(exc.value)


@pytest.mark.parametrize(
    "skus, price, fragment",
    [
        (["JKT-01-BR-L", "TEE-01-OL-M"], 110, "not in the buyer's sizes"),
        (["JKT-04-NY-M", "TEE-01-OL-M"], 110, "colors the buyer avoids"),
        (["TEE-01-OL-M", "PNT-01-OL-32"], 100, "must include a jacket"),
        (["JKT-02-OL-M", "BLZ-01-NV-M", "BOT-01-BR-10"], 450, "over the buyer's budget"),
    ],
)
def test_validation_enforces_buyer_rules(items, skus, price, fragment):
    inv = {i.sku: i for i in items}
    validate_bundles([_draft(skus, price)], inv, 1, 1)  # fine without the brief
    with pytest.raises(ValidationFailed) as exc:
        validate_bundles([_draft(skus, price)], inv, 1, 1, brief=BRIEF)
    assert fragment in str(exc.value)
