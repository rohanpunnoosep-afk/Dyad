"""The buyer's hard rules, checked in code.

One source of truth for the buyer agent's facts, the seller agent's inventory filter and the
middle man's validation, so all three agree on what "breaks a rule" means.

Enforced here: stock, sizes, colors_avoid, budget, and notes of the form "must include a <thing>".
Other notes ("no graphic prints") are free text: they go to both agents as strict rules, and the
buyer agent rates a bundle that breaks one at 0.1 or lower.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from models.schemas import BuyerBrief, Item

ONE_SIZE = {"os", "one size", "onesize"}

_MUST_INCLUDE = re.compile(r"^\s*must\s+(?:include|have)\s+(?:an?\s+|some\s+|one\s+)?(.+?)\s*$", re.I)


def norm(s: object) -> str:
    return str(s).strip().lower()


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def buyer_sizes(brief: BuyerBrief) -> set:
    return {norm(s) for s in brief.sizes.model_dump().values() if s}


def size_ok(brief: BuyerBrief, item: Item) -> Optional[bool]:
    """True/False when the buyer gave sizes, None when they gave none."""
    sizes = buyer_sizes(brief)
    if not sizes:
        return None
    return norm(item.size) in ONE_SIZE or norm(item.size) in sizes


def avoid_hits(brief: BuyerBrief, item: Item) -> List[str]:
    """Avoided colors that appear in the item's color or name."""
    haystack = f"{norm(item.color)} {norm(item.name)}"
    return [c for c in (norm(a) for a in brief.colors_avoid) if c and c in haystack]


def required_things(brief: BuyerBrief) -> List[str]:
    """Things a "must include a ..." note requires, e.g. ["jacket"]."""
    out = []
    for note in brief.notes:
        m = _MUST_INCLUDE.match(note)
        if m:
            out.append(_singular(norm(m.group(1))))
    return out


def satisfies(thing: str, item: Item) -> bool:
    words = {_singular(w) for w in re.findall(r"[a-z]+", f"{norm(item.category)} {norm(item.name)}")}
    return all(_singular(w) in words for w in thing.split())


def missing_required(brief: BuyerBrief, items: Sequence[Item]) -> List[str]:
    return [t for t in required_things(brief) if not any(satisfies(t, i) for i in items)]


def eligible(brief: BuyerBrief, item: Item) -> bool:
    """In stock, in the buyer's size, and not an avoided color."""
    return item.in_stock and size_ok(brief, item) is not False and not avoid_hits(brief, item)


def items_total(items: Iterable[Item]) -> float:
    return round(sum(i.price for i in items), 2)
