"""The middle man: drives buyer agent <-> seller agent through one round of 5 bundles.

BRIEF -> PROPOSE -> JUDGE -> ANALYZE -> FINAL -> DECIDE -> DONE

Each step reads its inputs from the repo, calls the agents, validates the result, and
finishes with one atomic `repo.commit_step`. A run can therefore stop anywhere
(function timeout, crash, lost lease) and a later run resumes from the saved step.
Message shapes follow json_formats.md.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from agents import buyer, seller
from db.repo import Repo
from middleman import analysis as analysis_mod
from middleman import rules
from middleman.heat import compute_item_heat
from middleman.validation import ValidationFailed, clamp_probability, validate_bundles
from models.schemas import (
    AnalysisDraft,
    Bundle,
    BundleDraft,
    BuyerBrief,
    HeatLabel,
    Item,
    ItemHeat,
    Judgment,
    JudgmentDraft,
    Negotiation,
    Status,
    Step,
)

log = logging.getLogger("brojans.middleman")

LEASE_SECONDS = 180
BUNDLES_PER_ROUND = 5
ROUND = 1
FINAL_ROUND = 2
MAX_ATTEMPTS = 2  # first try + one re-prompt carrying the validation errors


class Agents:
    """The buyer and seller agents the orchestrator calls. Tests swap in a fake."""

    async def build_brief(self, buyer_input: str) -> BuyerBrief:
        return await buyer.build_brief(buyer_input)

    async def rate_bundles(
        self, brief: BuyerBrief, bundles: Sequence[Bundle], inventory: Dict[str, Item]
    ) -> List[JudgmentDraft]:
        return await buyer.rate_bundles(brief, bundles, inventory)

    async def decide(self, brief: BuyerBrief, bundle: Bundle, inventory: Dict[str, Item]) -> JudgmentDraft:
        return await buyer.decide(brief, bundle, inventory)

    async def propose_bundles(self, brief, inventory, count, errors=None) -> List[BundleDraft]:
        return await seller.propose_bundles(brief, inventory, count, errors)

    async def analyze_round(self, brief, keyed, judgments, inventory, heat, attribute_avgs,
                            check_keys) -> AnalysisDraft:
        return await seller.analyze_round(brief, keyed, judgments, inventory, heat, attribute_avgs, check_keys)

    async def final_bundle(self, brief, inventory, keyed, judgments, analysis, errors=None) -> List[BundleDraft]:
        return await seller.final_bundle(brief, inventory, keyed, judgments, analysis, errors)


class LeaseLost(Exception):
    pass


def keyed_bundles(bundles: Sequence[Bundle]) -> Dict[str, Bundle]:
    """The B1..Bn labels both agents see, in proposal order."""
    return {f"B{n}": b for n, b in enumerate(bundles, start=1)}


def bundle_view(bundle: Bundle, inventory: Mapping[str, Item]) -> Dict[str, Any]:
    """A bundle as sent to the buyer (json_formats.md section 3). Totals are computed here."""
    items = [inventory[s] for s in bundle.skus if s in inventory]
    return {
        "id": bundle.id,
        "name": bundle.name,
        "skus": bundle.skus,
        "images": [i.image for i in items],
        "items_total": rules.items_total(items),
        "price": bundle.price,
        "pitch": bundle.pitch,
    }


class _Run:
    def __init__(self, repo: Repo, negotiation_id: str, owner: str, agents: Agents):
        self.repo, self.id, self.owner, self.agents = repo, negotiation_id, owner, agents
        self._inventory: Optional[List[Item]] = None

    async def inventory(self) -> List[Item]:
        if self._inventory is None:
            self._inventory = await self.repo.list_items()
        return self._inventory

    async def inventory_by_sku(self) -> Dict[str, Item]:
        return {i.sku: i for i in await self.inventory()}

    async def commit(self, from_step: Step, to_step: Step, **kwargs) -> None:
        ok = await self.repo.commit_step(self.id, self.owner, from_step, to_step,
                                         lease_seconds=LEASE_SECONDS, **kwargs)
        if not ok:
            raise LeaseLost(f"lost lease or step moved while committing {from_step.value}")

    async def validated(
        self,
        stage: str,
        brief: BuyerBrief,
        produce: Callable[[Optional[List[str]]], Awaitable[List[BundleDraft]]],
        count: int,
        banned: Set[str],
    ) -> Tuple[List[BundleDraft], Dict[str, Any]]:
        """Seller output that passed validation, plus the check event (json_formats.md section 4)."""
        inventory = await self.inventory_by_sku()
        errors: Optional[List[str]] = None
        rejected: List[List[str]] = []
        for attempt in range(MAX_ATTEMPTS):
            drafts = await produce(errors)
            try:
                validate_bundles(drafts, inventory, count, count, banned, brief)
                return drafts, {"stage": stage, "valid": True, "errors": [], "rejected_attempts": rejected}
            except ValidationFailed as e:
                log.warning("negotiation %s: seller output rejected (attempt %d): %s", self.id, attempt + 1, e)
                errors = e.errors
                rejected.append(e.errors)
        raise ValidationFailed(errors or ["seller output invalid"])

    def to_bundles(self, drafts: Sequence[BundleDraft], round_: int) -> List[Bundle]:
        return [Bundle(id=str(uuid.uuid4()), negotiation_id=self.id, round=round_, **d.model_dump())
                for d in drafts]

    async def round_state(self) -> Tuple[Dict[str, Bundle], List[Judgment], List[ItemHeat]]:
        bundles = await self.repo.list_bundles(self.id, ROUND)
        judgments = await self.repo.list_judgments(self.id, ROUND)
        heat = await self.repo.list_item_heat(self.id, ROUND)
        return keyed_bundles(bundles), judgments, heat

    # ---------------------------------------------------------------- steps

    async def step_brief(self, neg: Negotiation) -> None:
        brief = await self.agents.build_brief(neg.buyer_input)
        await self.commit(Step.BRIEF, Step.PROPOSE, brief=brief, events=[("brief", brief.model_dump())])

    async def step_propose(self, neg: Negotiation) -> None:
        inv = await self.inventory()
        drafts, check = await self.validated(
            "bundles", neg.brief,
            lambda errs: self.agents.propose_bundles(neg.brief, inv, BUNDLES_PER_ROUND, errs),
            BUNDLES_PER_ROUND, banned=set(),
        )
        bundles = self.to_bundles(drafts, ROUND)
        by_sku = await self.inventory_by_sku()
        payload = {"round": ROUND, "bundles": [bundle_view(b, by_sku) for b in bundles]}
        await self.commit(Step.PROPOSE, Step.JUDGE, bundles=bundles,
                          events=[("check", check), ("bundles_proposed", payload)])

    async def step_judge(self, neg: Negotiation) -> None:
        bundles = await self.repo.list_bundles(self.id, ROUND)
        inventory = await self.inventory_by_sku()
        drafts = await self.agents.rate_bundles(neg.brief, bundles, inventory)
        if len(drafts) != len(bundles):
            raise ValueError(f"buyer agent returned {len(drafts)} ratings for {len(bundles)} bundles")
        judgments = [
            Judgment(bundle_id=b.id, negotiation_id=self.id, round=ROUND,
                     **{**d.model_dump(), "probability": clamp_probability(d.probability)})
            for b, d in zip(bundles, drafts)
        ]
        heat = compute_item_heat(bundles, judgments)
        ratings = {"round": ROUND, "ratings": [
            {"id": j.bundle_id, **j.model_dump(exclude={"bundle_id", "negotiation_id", "round"})} for j in judgments
        ]}
        events = [("ratings", ratings),
                  ("heat", {"round": ROUND, "items": [h.model_dump(mode="json") for h in heat]})]
        await self.commit(Step.JUDGE, Step.ANALYZE, judgments=judgments, heat_round=ROUND, heat=heat, events=events)

    async def step_analyze(self, neg: Negotiation) -> None:
        keyed, judgments, heat = await self.round_state()
        inventory = await self.inventory_by_sku()
        attr_avgs = analysis_mod.attribute_averages(list(keyed.values()), judgments, inventory)
        check_keys = analysis_mod.low_bundle_keys(keyed, judgments)
        draft = await self.agents.analyze_round(neg.brief, keyed, judgments, inventory, heat, attr_avgs, check_keys)
        result = analysis_mod.finalize(draft, ROUND, keyed, judgments, inventory, heat)
        await self.commit(Step.ANALYZE, Step.FINAL, analysis=result,
                          events=[("analysis", result.model_dump(mode="json"))])

    async def step_final(self, neg: Negotiation) -> None:
        inv = await self.inventory()
        keyed, judgments, heat = await self.round_state()
        result = await self.repo.get_analysis(self.id, ROUND)
        if result is None:
            raise ValueError("no analysis saved for the round")
        banned = set(result.drop_skus) | {h.sku for h in heat if h.label == HeatLabel.COLD}
        drafts, check = await self.validated(
            "final", neg.brief,
            lambda errs: self.agents.final_bundle(neg.brief, inv, keyed, judgments, result, errs),
            1, banned=banned,
        )
        [bundle] = self.to_bundles(drafts, FINAL_ROUND)
        inventory = await self.inventory_by_sku()
        view = bundle_view(bundle, inventory)
        view["savings"] = round(view["items_total"] - bundle.price, 2)
        view["why"] = view.pop("pitch")
        offer = {"final": view, "items": [inventory[s].model_dump() for s in bundle.skus]}
        await self.commit(Step.FINAL, Step.DECIDE, bundles=[bundle],
                          events=[("check", check), ("final_offer", offer)])

    async def step_decide(self, neg: Negotiation) -> None:
        [bundle] = await self.repo.list_bundles(self.id, FINAL_ROUND)
        d = await self.agents.decide(neg.brief, bundle, await self.inventory_by_sku())
        if d.decision not in ("accept", "reject"):
            raise ValueError(f"buyer agent returned decision {d.decision!r}")
        judgment = Judgment(bundle_id=bundle.id, negotiation_id=self.id, round=FINAL_ROUND,
                            **{**d.model_dump(), "probability": clamp_probability(d.probability)})
        decision = {"id": bundle.id, "decision": judgment.decision, "probability": judgment.probability,
                    "reason": judgment.reason}
        await self.commit(Step.DECIDE, Step.DONE, status=Status.DONE, judgments=[judgment],
                          events=[("decision", decision), ("done", {})])


async def run_negotiation(repo: Repo, negotiation_id: str, owner: str, agents: Optional[Agents] = None) -> None:
    """Run from the saved step to DONE. The caller must already hold the lease."""
    run = _Run(repo, negotiation_id, owner, agents or Agents())
    steps = {
        Step.BRIEF: run.step_brief,
        Step.PROPOSE: run.step_propose,
        Step.JUDGE: run.step_judge,
        Step.ANALYZE: run.step_analyze,
        Step.FINAL: run.step_final,
        Step.DECIDE: run.step_decide,
    }
    try:
        while True:
            neg = await repo.get_negotiation(negotiation_id)
            if neg is None or neg.status in (Status.DONE, Status.FAILED) or neg.step == Step.DONE:
                return
            log.info("negotiation %s: running %s", negotiation_id, neg.step.value)
            await steps[neg.step](neg)
    except LeaseLost as e:
        log.warning("negotiation %s: %s", negotiation_id, e)
    except Exception as e:  # noqa: BLE001 - any agent/validation failure ends the run as failed
        log.exception("negotiation %s failed", negotiation_id)
        await repo.mark_failed(negotiation_id, owner, f"{type(e).__name__}: {e}")
    finally:
        await repo.release_lease(negotiation_id, owner)
