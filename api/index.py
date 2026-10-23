"""Brojans middle man API (FastAPI on Vercel's Python runtime)."""

from __future__ import annotations

import os
import sys
import uuid
from typing import Optional

# Vercel runs this file as the function entrypoint; make the project root importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from db.repo import make_repo  # noqa: E402
from middleman.events import stream_negotiation  # noqa: E402
from middleman.orchestrator import FINAL_ROUND  # noqa: E402
from models.schemas import BuyerBrief, Status  # noqa: E402

app = FastAPI(title="Brojans middle man")
app.state.make_repo = make_repo
app.state.agents = None  # None = real OpenAI-backed agents; tests inject fakes


class CreateNegotiation(BaseModel):
    buyer_input: str = Field(min_length=1, max_length=20000)
    # Optional pre-built buyer context (json_formats.md section 2); when given, the BRIEF step is skipped.
    brief: Optional[BuyerBrief] = None


def _check_id(negotiation_id: str) -> str:
    try:
        return str(uuid.UUID(negotiation_id))
    except ValueError:
        raise HTTPException(404, "negotiation not found")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.post("/api/negotiations", status_code=201)
async def create_negotiation(body: CreateNegotiation, request: Request):
    repo = request.app.state.make_repo()
    try:
        neg = await repo.create_negotiation(body.buyer_input, body.brief)
    finally:
        await repo.close()
    return {"id": neg.id, "stream_url": f"/api/negotiations/{neg.id}/stream"}


@app.get("/api/negotiations/{negotiation_id}")
async def get_negotiation(negotiation_id: str, request: Request):
    negotiation_id = _check_id(negotiation_id)
    repo = request.app.state.make_repo()
    try:
        neg = await repo.get_negotiation(negotiation_id)
        if neg is None:
            raise HTTPException(404, "negotiation not found")
        bundles = await repo.list_bundles(negotiation_id)
        judgments = {j.bundle_id: j for j in await repo.list_judgments(negotiation_id)}
        rounds = []
        for r in sorted({b.round for b in bundles if b.round != FINAL_ROUND}):
            analysis = await repo.get_analysis(negotiation_id, r)
            rounds.append({
                "round": r,
                "bundles": [
                    {**b.model_dump(), "judgment": judgments[b.id].model_dump() if b.id in judgments else None}
                    for b in bundles if b.round == r
                ],
                "heat": [h.model_dump(mode="json") for h in await repo.list_item_heat(negotiation_id, r)],
                "analysis": analysis.model_dump(mode="json") if analysis else None,
            })
    finally:
        await repo.close()
    final = next((b for b in bundles if b.round == FINAL_ROUND), None)
    decision = judgments.get(final.id) if final else None
    return {
        "negotiation": neg.model_dump(mode="json", exclude={"buyer_input"}),
        "rounds": rounds,
        "final_offer": final.model_dump() if final else None,
        "decision": decision.model_dump(include={"decision", "probability", "reason"}) if decision else None,
    }


@app.get("/api/negotiations/{negotiation_id}/stream")
async def stream(
    negotiation_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: Optional[str] = Header(None),
):
    """SSE: replays events after `after` (or Last-Event-ID), then runs/resumes and tails live."""
    negotiation_id = _check_id(negotiation_id)
    repo = request.app.state.make_repo()
    try:
        if await repo.get_negotiation(negotiation_id) is None:
            raise HTTPException(404, "negotiation not found")
    finally:
        await repo.close()
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    return StreamingResponse(
        stream_negotiation(negotiation_id, after, request.app.state.make_repo, request.app.state.agents),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.post("/api/negotiations/{negotiation_id}/retry")
async def retry(negotiation_id: str, request: Request):
    """Re-arm a failed negotiation. It resumes from the step that failed on the next stream open."""
    negotiation_id = _check_id(negotiation_id)
    repo = request.app.state.make_repo()
    try:
        neg = await repo.get_negotiation(negotiation_id)
        if neg is None:
            raise HTTPException(404, "negotiation not found")
        if neg.status != Status.FAILED or not await repo.reset_failed(negotiation_id):
            raise HTTPException(409, f"negotiation is {neg.status.value}, not failed")
    finally:
        await repo.close()
    return {"id": negotiation_id, "step": neg.step.value, "stream_url": f"/api/negotiations/{negotiation_id}/stream"}
