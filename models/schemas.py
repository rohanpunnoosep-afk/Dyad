"""Shared data shapes for the middle man, the buyer agent and the seller agent.

Message shapes follow json_formats.md. Prices are dollars everywhere.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Step(str, Enum):
    """Negotiation state machine (single round). Each step is resumable from the DB."""

    BRIEF = "BRIEF"
    PROPOSE = "PROPOSE"
    JUDGE = "JUDGE"
    ANALYZE = "ANALYZE"
    FINAL = "FINAL"
    DECIDE = "DECIDE"
    DONE = "DONE"


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class HeatLabel(str, Enum):
    HOT = "hot"
    NEUTRAL = "neutral"
    COLD = "cold"


class Item(BaseModel):
    """One SKU of seller inventory (json_formats.md section 1). Each size is its own SKU."""

    sku: str
    name: str
    category: str
    color: str
    material: str
    size: str
    price: float
    stock: int = Field(ge=0)
    image: str
    margin_pct: float = 50.0  # gross margin % of the price. Seller-only: never shown to the buyer agent
    delivery_days: int = 5    # average days to deliver this item with standard shipping

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


# ---- LLM output shapes (kept constraint-free so they work as structured-output schemas;
# ---- range and rule checks live in middleman/validation.py and middleman/analysis.py) ----


class Sizes(BaseModel):
    top: Optional[str] = None
    bottom: Optional[str] = None
    shoe: Optional[str] = None


Shipping = Literal["standard", "express", "priority"]
ReturnWindow = Literal["2 weeks", "2 months", "6 months"]
RefundPct = Literal[30, 75, 100]


class BuyerBrief(BaseModel):
    """The buyer context (json_formats.md section 2). `notes` are strict rules."""

    style: List[str]  # as many descriptive style keywords as the buyer's input supports
    colors_liked: List[str]
    colors_avoid: List[str]
    sizes: Sizes
    budget: Optional[float] = None
    occasion: Optional[str] = None
    notes: List[str]
    additional_notes: Optional[str] = None   # the buyer's own words about what they want (soft)
    needed_by: Optional[str] = None          # when they want the clothes, as they said it
    delivery_days: Optional[int] = None      # wants delivery within this many days
    returns_note: Optional[str] = None       # how much being able to return matters to them
    return_window: Optional[ReturnWindow] = None  # how long they want the return guarantee to run


class BundleProposal(BaseModel):
    """What the seller's model proposes. The price comes from middleman/pricing.py."""

    name: str
    skus: List[str]
    shipping: Shipping
    return_window: ReturnWindow
    refund_pct: RefundPct
    pitch: str


class ProposalSet(BaseModel):
    bundles: List[BundleProposal]


class BundleDraft(BaseModel):
    name: str
    skus: List[str]
    price: float
    pitch: str
    shipping: Shipping = "standard"
    delivery_days: int = 0
    return_window: ReturnWindow = "2 weeks"
    refund_pct: RefundPct = 30


class JudgmentDraft(BaseModel):
    probability: float
    reason: str
    # Sub-scores (0-1) behind the probability. Optional so older rows still load.
    price_score: Optional[float] = None
    fit_score: Optional[float] = None
    style_score: Optional[float] = None
    decision: Optional[str] = None  # "accept" | "reject", only on the final offer


class DecisionDraft(BaseModel):
    """The buyer agent's answer to the final offer (json_formats.md section 8)."""

    decision: Literal["accept", "reject"]
    probability: float
    reason: str


class BundleRating(BaseModel):
    """The buyer agent's rating of one bundle, keyed by the label it was shown (B1, B2, ...)."""

    bundle_key: str
    price_score: float
    fit_score: float
    style_score: float
    probability: float
    reason: str


class BundleRatingSet(BaseModel):
    ratings: List[BundleRating]


Dimension = Literal["category", "style", "color", "material", "size", "price", "fit"]


class ItemStyle(BaseModel):
    sku: str
    style: str


class ItemCheckDraft(BaseModel):
    bundle_key: str
    sku: str
    verdict: Literal["hurts", "neutral", "helps"]
    dimension: Literal["category", "style", "color", "material", "size", "price", "fit", "none"]
    note: str


class SignalDraft(BaseModel):
    type: Dimension
    value: str


class AnalysisDraft(BaseModel):
    """What the seller's analyst returns. The middle man adds the numbers (see RoundAnalysis)."""

    item_styles: List[ItemStyle]
    item_checks: List[ItemCheckDraft]
    works: List[SignalDraft]
    fails: List[SignalDraft]
    keep_skus: List[str]
    drop_skus: List[str]
    main_issue: Literal["category", "style", "color", "material", "size", "price", "fit", "none"]


# ---- Persisted records ----


class Bundle(BundleDraft):
    id: str
    negotiation_id: str
    round: int


class Judgment(JudgmentDraft):
    bundle_id: str
    negotiation_id: str
    round: int


class ItemHeat(BaseModel):
    sku: str
    score: float
    label: HeatLabel
    bundle_count: int


class ItemCheck(BaseModel):
    bundle_id: str
    sku: str
    verdict: str
    dimension: str
    note: str


class Signal(BaseModel):
    type: str
    value: str
    avg_prob: Optional[float] = None
    votes: int = 0
    confirmed: bool = False


class RoundAnalysis(BaseModel):
    """Seller analysis of a judged round (json_formats.md section 6)."""

    round: int
    avg: float
    subscore_avgs: Dict[str, float]
    attribute_avgs: Dict[str, Dict[str, float]]
    item_checks: List[ItemCheck]
    works: List[Signal]
    fails: List[Signal]
    keep_skus: List[str]
    drop_skus: List[str]
    main_issue: str


class Negotiation(BaseModel):
    id: str
    buyer_input: str
    brief: Optional[BuyerBrief] = None
    status: Status = Status.PENDING
    step: Step = Step.BRIEF
    error: Optional[str] = None


class Event(BaseModel):
    id: int
    negotiation_id: str
    type: str
    payload: Dict[str, Any]
    ts: datetime
