"""SSE stream for a negotiation: replay past events, run or resume the negotiation, tail new events.

Whoever opens the stream either takes the lease and runs the orchestrator in this
invocation, or (when another invocation already holds it) just tails the events table.
A tailing stream keeps trying to take the lease, so if the runner dies (for example on a
function timeout) the next open stream picks the negotiation up from its saved step.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator, Callable, Optional

from db.repo import Repo
from middleman.orchestrator import LEASE_SECONDS, Agents, run_negotiation
from models.schemas import Event, Status

POLL_SECONDS = 1.0
TAKEOVER_CHECK_SECONDS = 5.0
KEEPALIVE_SECONDS = 15.0
TERMINAL = (Status.DONE, Status.FAILED)


def format_sse(ev: Event) -> str:
    data = json.dumps({"id": ev.id, "type": ev.type, "payload": ev.payload, "ts": ev.ts.isoformat()}, default=str)
    return f"id: {ev.id}\nevent: {ev.type}\ndata: {data}\n\n"


async def stream_negotiation(
    negotiation_id: str,
    after: int,
    make_repo: Callable[[], Repo],
    agents: Optional[Agents] = None,
    poll_seconds: float = POLL_SECONDS,
) -> AsyncIterator[str]:
    tail = make_repo()
    owner = f"stream-{uuid.uuid4()}"
    task: Optional[asyncio.Task] = None

    async def try_start_runner() -> Optional[asyncio.Task]:
        run_repo = make_repo()
        if not await run_repo.acquire_lease(negotiation_id, owner, LEASE_SECONDS):
            await run_repo.close()
            return None

        async def _run() -> None:
            try:
                await run_negotiation(run_repo, negotiation_id, owner, agents)
            finally:
                await run_repo.close()

        return asyncio.create_task(_run())

    try:
        last = after
        last_sent = time.monotonic()
        last_takeover_check = float("-inf")
        while True:
            # Read status before events: status and events commit atomically, so a terminal
            # status seen here guarantees the events read next are complete.
            neg = await tail.get_negotiation(negotiation_id)
            if neg is None:
                return
            terminal = neg.status in TERMINAL

            for ev in await tail.list_events(negotiation_id, last):
                yield format_sse(ev)
                last, last_sent = ev.id, time.monotonic()
            if terminal:
                return

            now = time.monotonic()
            if (task is None or task.done()) and now - last_takeover_check >= TAKEOVER_CHECK_SECONDS:
                last_takeover_check = now
                task = await try_start_runner() or task
            if now - last_sent >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_sent = now
            await asyncio.sleep(poll_seconds)
    finally:
        # A client disconnect does not cancel a runner: it keeps going best-effort, and if
        # the function is frozen the lease expires and the next stream resumes the run.
        await tail.close()
