import asyncio

from middleman.orchestrator import FINAL_ROUND, ROUND, run_negotiation
from models.schemas import Status, Step
from tests.conftest import COLD_ITEM, FINAL_SKUS, HOT_ITEM, FakeAgents


def run(coro):
    return asyncio.run(coro)


async def _create_and_run(repo, agents, owner="o1"):
    neg = await repo.create_negotiation("I like workwear, size M")
    assert await repo.acquire_lease(neg.id, owner, 60)
    await run_negotiation(repo, neg.id, owner, agents)
    return neg.id


def test_full_run_one_round_of_five_then_analysis_and_final(repo, items):
    agents = FakeAgents(items)

    async def go():
        nid = await _create_and_run(repo, agents)
        neg = await repo.get_negotiation(nid)
        assert neg.status == Status.DONE and neg.step == Step.DONE
        assert len(await repo.list_bundles(nid, ROUND)) == 5
        assert len(await repo.list_judgments(nid, ROUND)) == 5
        [final] = await repo.list_bundles(nid, FINAL_ROUND)
        assert final.skus == FINAL_SKUS and COLD_ITEM not in final.skus

        heat = {h.sku: h.label.value for h in await repo.list_item_heat(nid, ROUND)}
        assert heat[HOT_ITEM] == "hot" and heat[COLD_ITEM] == "cold"

        analysis = await repo.get_analysis(nid, ROUND)
        assert analysis.main_issue == "style"
        assert COLD_ITEM in analysis.drop_skus and "JKT-03-NV-M" in analysis.drop_skus  # cold via heat
        assert {c.sku for c in analysis.item_checks} == {"JKT-03-NV-M", COLD_ITEM, "TRS-01-GR-32"}
        formal = next(f for f in analysis.fails if f.value == "formal")
        assert formal.confirmed and formal.votes == 2 and formal.avg_prob == 0.1

        events = await repo.list_events(nid)
        assert [e.type for e in events] == [
            "brief", "check", "bundles_proposed", "ratings", "heat", "analysis", "check", "final_offer",
            "decision", "done",
        ]
        proposed = events[2].payload["bundles"]
        assert len(proposed) == 5
        assert proposed[0]["images"] == [f"{s}.jpg" for s in proposed[0]["skus"]]
        offer = events[-3].payload["final"]
        assert events[-2].payload["decision"] == "accept" and events[-2].payload["id"] == final.id
        [decision] = await repo.list_judgments(nid, FINAL_ROUND)
        assert decision.decision == "accept" and decision.probability == 0.88
        assert offer["skus"] == FINAL_SKUS
        assert offer["savings"] == round(offer["items_total"] - offer["price"], 2)
        assert offer["why"] == "pitch for final"

    run(go())
    assert agents.seen["check_keys"] == ["B2"]  # only the formal bundle is below 0.5
    assert "style" not in agents.seen["attribute_avgs"]  # style averages need the analyst's labels
    assert agents.calls["rate_bundles"] == 1


def test_invalid_bundles_are_reprompted_with_errors(repo, items):
    agents = FakeAgents(items, bad_first="propose_bundles")

    async def go():
        nid = await _create_and_run(repo, agents)
        assert (await repo.get_negotiation(nid)).status == Status.DONE
        check = (await repo.list_events(nid))[1].payload
        assert check["valid"] and len(check["rejected_attempts"]) == 1

    run(go())
    first, second = agents.seen["propose_errors"]
    assert first is None
    assert any("must include a jacket" in e for e in second)


def test_final_bundle_cannot_use_dropped_items(repo, items):
    agents = FakeAgents(items, bad_first="final_bundle")

    async def go():
        nid = await _create_and_run(repo, agents)
        assert (await repo.get_negotiation(nid)).status == Status.DONE

    run(go())
    assert any(COLD_ITEM in e and "rejected" in e for e in agents.seen["final_errors"][1])


def test_failure_marks_failed_then_retry_resumes_without_redoing_steps(repo, items):
    agents = FakeAgents(items, fail_on="analyze_round")

    async def go():
        nid = await _create_and_run(repo, agents)
        neg = await repo.get_negotiation(nid)
        assert neg.status == Status.FAILED and neg.step == Step.ANALYZE
        assert "boom in analyze_round" in neg.error
        assert (await repo.list_events(nid))[-1].type == "error"

        assert await repo.reset_failed(nid)
        assert await repo.acquire_lease(nid, "o2", 60)
        await run_negotiation(repo, nid, "o2", agents)
        assert (await repo.get_negotiation(nid)).status == Status.DONE
        assert len(await repo.list_bundles(nid, ROUND)) == 5  # proposals were not redone

    run(go())
    assert agents.calls["build_brief"] == 1
    assert agents.calls["propose_bundles"] == 1
    assert agents.calls["rate_bundles"] == 1


def test_lease_is_exclusive_and_stale_owner_cannot_commit(repo, items):
    async def go():
        neg = await repo.create_negotiation("hi")
        assert await repo.acquire_lease(neg.id, "a", 60)
        assert not await repo.acquire_lease(neg.id, "b", 60)
        # "b" never got the lease, so its run must not write anything
        await run_negotiation(repo, neg.id, "b", FakeAgents(items))
        assert (await repo.get_negotiation(neg.id)).step == Step.BRIEF
        assert await repo.list_events(neg.id) == []

    run(go())


def test_prebuilt_brief_skips_brief_step(repo, items):
    from tests.conftest import BRIEF

    agents = FakeAgents(items)

    async def go():
        neg = await repo.create_negotiation("from buyer side", BRIEF)
        assert neg.step == Step.PROPOSE
        assert await repo.acquire_lease(neg.id, "o", 60)
        await run_negotiation(repo, neg.id, "o", agents)
        assert (await repo.get_negotiation(neg.id)).status == Status.DONE

    run(go())
    assert "build_brief" not in agents.calls
