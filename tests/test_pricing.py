import pytest

from middleman import pricing
from models.schemas import Item


def _item(sku, price, margin, days):
    return Item(sku=sku, name=sku, category="tee", color="white", material="cotton", size="M", price=price,
                stock=1, image=f"{sku}.jpg", margin_pct=margin, delivery_days=days)


LOW = [_item("a", 100, 35, 3), _item("b", 100, 35, 6)]
HIGH = [_item("c", 100, 70, 3), _item("d", 100, 70, 6)]


def test_more_margin_means_a_bigger_discount():
    low, high = (pricing.quote(x, "standard", "2 weeks", 30) for x in (LOW, HIGH))
    assert low.margin_pct == 35 and low.margin_discount_pct == 0
    assert high.margin_pct == 70 and high.margin_discount_pct == 15
    assert high.price < low.price
    assert pricing.margin_discount(95) == pricing.MAX_MARGIN_DISCOUNT_PCT
    assert pricing.margin_discount(30) == 0 and pricing.margin_discount(50) == 5


def test_aggregate_margin_is_price_weighted():
    assert pricing.aggregate_margin([_item("a", 300, 40, 1), _item("b", 100, 80, 1)]) == 50


def test_faster_shipping_arrives_sooner_and_costs_more():
    quotes = [pricing.quote(LOW, s, "2 weeks", 30) for s in ("standard", "express", "priority")]
    assert [q.delivery_days for q in quotes] == [6, 3, 2]
    assert quotes[0].price < quotes[1].price < quotes[2].price


def test_buyers_in_a_hurry_pay_a_rush_premium():
    prices = [pricing.quote(LOW, "standard", "2 weeks", 30, days).price for days in (None, 10, 4, 2)]
    assert prices[0] == prices[1] < prices[2] < prices[3]


@pytest.mark.parametrize("window", list(pricing.RETURN_WINDOWS))
def test_more_money_back_costs_more(window):
    prices = [pricing.quote(LOW, "standard", window, r).price for r in pricing.REFUND_PCTS]
    assert prices == sorted(prices) and len(set(prices)) == 3


@pytest.mark.parametrize("refund", pricing.REFUND_PCTS)
def test_longer_return_windows_cost_more(refund):
    prices = [pricing.quote(LOW, "standard", w, refund).price for w in pricing.RETURN_WINDOWS]
    assert prices == sorted(prices) and len(set(prices)) == 3
