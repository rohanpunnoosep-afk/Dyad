"""Persistence for negotiations.

Every orchestrator step finishes with one atomic `commit_step`, which writes the step's
outputs, appends its events and advances `step`. The write only applies while the caller
still holds the lease and the negotiation is still at `from_step`. That makes steps
idempotent: a run that crashes mid-step simply redoes that step on resume.

`PostgresRepo` is used whenever DATABASE_URL is set (Vercel + Neon). `MemoryRepo` is
for tests and local dev only, because its state does not survive across serverless instances.
"""

from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from models.schemas import (
    Bundle,
    BuyerBrief,
    Event,
    HeatLabel,
    Item,
    ItemHeat,
    Judgment,
    Negotiation,
    RoundAnalysis,
    Status,
    Step,
)

EventSpec = Tuple[str, Dict[str, Any]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Repo(ABC):
    @abstractmethod
    async def create_negotiation(self, buyer_input: str, brief: Optional[BuyerBrief] = None) -> Negotiation: ...

    @abstractmethod
    async def get_negotiation(self, negotiation_id: str) -> Optional[Negotiation]: ...

    @abstractmethod
    async def acquire_lease(self, negotiation_id: str, owner: str, seconds: int) -> bool: ...

    @abstractmethod
    async def release_lease(self, negotiation_id: str, owner: str) -> None: ...

    @abstractmethod
    async def list_items(self) -> List[Item]: ...

    @abstractmethod
    async def list_bundles(self, negotiation_id: str, round: Optional[int] = None) -> List[Bundle]: ...

    @abstractmethod
    async def list_judgments(self, negotiation_id: str, round: Optional[int] = None) -> List[Judgment]: ...

    @abstractmethod
    async def list_item_heat(self, negotiation_id: str, round: int) -> List[ItemHeat]: ...

    @abstractmethod
    async def get_analysis(self, negotiation_id: str, round: int) -> Optional[RoundAnalysis]: ...

    @abstractmethod
    async def list_events(self, negotiation_id: str, after: int = 0) -> List[Event]: ...

    @abstractmethod
    async def commit_step(
        self,
        negotiation_id: str,
        owner: str,
        from_step: Step,
        to_step: Step,
        *,
        lease_seconds: int,
        status: Status = Status.RUNNING,
        brief: Optional[BuyerBrief] = None,
        bundles: Sequence[Bundle] = (),
        judgments: Sequence[Judgment] = (),
        heat_round: Optional[int] = None,
        heat: Sequence[ItemHeat] = (),
        analysis: Optional[RoundAnalysis] = None,
        events: Sequence[EventSpec] = (),
    ) -> bool:
        """Atomically persist a finished step. Returns False if the lease or step was lost."""

    @abstractmethod
    async def mark_failed(self, negotiation_id: str, owner: str, error: str) -> None: ...

    @abstractmethod
    async def reset_failed(self, negotiation_id: str) -> bool: ...

    async def close(self) -> None:
        pass


# --------------------------------------------------------------------------- memory


class _MemoryStore:
    def __init__(self) -> None:
        self.items: Dict[str, Item] = {}
        self.negotiations: Dict[str, Dict[str, Any]] = {}
        self.bundles: List[Bundle] = []
        self.judgments: List[Judgment] = []
        self.heat: Dict[Tuple[str, int], List[ItemHeat]] = {}
        self.analyses: Dict[Tuple[str, int], RoundAnalysis] = {}
        self.events: List[Event] = []


_MEMORY = _MemoryStore()


class MemoryRepo(Repo):
    """In-process store. The asyncio loop is single-threaded and no method awaits midway,
    so each method is atomic."""

    def __init__(self, store: Optional[_MemoryStore] = None):
        self.s = store or _MEMORY

    def seed_items(self, items: Sequence[Item]) -> None:
        for item in items:
            self.s.items[item.sku] = item

    def _event(self, negotiation_id: str, type_: str, payload: Dict[str, Any]) -> Event:
        ev = Event(id=len(self.s.events) + 1, negotiation_id=negotiation_id, type=type_, payload=payload, ts=_now())
        self.s.events.append(ev)
        return ev

    async def create_negotiation(self, buyer_input, brief=None):
        neg = Negotiation(id=str(uuid.uuid4()), buyer_input=buyer_input, brief=brief,
                          step=Step.PROPOSE if brief else Step.BRIEF)
        self.s.negotiations[neg.id] = {"neg": neg, "lease_owner": None, "lease_until": None}
        if brief:
            self._event(neg.id, "brief", brief.model_dump())
        return neg

    async def get_negotiation(self, negotiation_id):
        row = self.s.negotiations.get(negotiation_id)
        return row["neg"].model_copy() if row else None

    async def acquire_lease(self, negotiation_id, owner, seconds):
        row = self.s.negotiations.get(negotiation_id)
        if row is None or row["neg"].status in (Status.DONE, Status.FAILED):
            return False
        if row["lease_until"] and row["lease_until"] > _now() and row["lease_owner"] != owner:
            return False
        row["lease_owner"], row["lease_until"] = owner, _now() + timedelta(seconds=seconds)
        row["neg"].status = Status.RUNNING
        return True

    async def release_lease(self, negotiation_id, owner):
        row = self.s.negotiations.get(negotiation_id)
        if row and row["lease_owner"] == owner:
            row["lease_owner"], row["lease_until"] = None, None

    async def list_items(self):
        return list(self.s.items.values())

    async def list_bundles(self, negotiation_id, round=None):
        return [b for b in self.s.bundles
                if b.negotiation_id == negotiation_id and (round is None or b.round == round)]

    async def list_judgments(self, negotiation_id, round=None):
        return [j for j in self.s.judgments
                if j.negotiation_id == negotiation_id and (round is None or j.round == round)]

    async def list_item_heat(self, negotiation_id, round):
        return list(self.s.heat.get((negotiation_id, round), []))

    async def get_analysis(self, negotiation_id, round):
        return self.s.analyses.get((negotiation_id, round))

    async def list_events(self, negotiation_id, after=0):
        return [e for e in self.s.events if e.negotiation_id == negotiation_id and e.id > after]

    async def commit_step(self, negotiation_id, owner, from_step, to_step, *, lease_seconds,
                          status=Status.RUNNING, brief=None, bundles=(), judgments=(),
                          heat_round=None, heat=(), analysis=None, events=()):
        row = self.s.negotiations.get(negotiation_id)
        if row is None or row["lease_owner"] != owner or row["neg"].step != from_step:
            return False
        neg: Negotiation = row["neg"]
        if brief is not None:
            neg.brief = brief
        self.s.bundles.extend(bundles)
        self.s.judgments.extend(judgments)
        if heat_round is not None:
            self.s.heat[(negotiation_id, heat_round)] = list(heat)
        if analysis is not None:
            self.s.analyses[(negotiation_id, analysis.round)] = analysis
        for type_, payload in events:
            self._event(negotiation_id, type_, payload)
        neg.step, neg.status = to_step, status
        row["lease_until"] = _now() + timedelta(seconds=lease_seconds)
        return True

    async def mark_failed(self, negotiation_id, owner, error):
        row = self.s.negotiations.get(negotiation_id)
        if row is None or row["lease_owner"] != owner:
            return
        row["neg"].status, row["neg"].error = Status.FAILED, error
        row["lease_owner"], row["lease_until"] = None, None
        self._event(negotiation_id, "error", {"message": error, "step": row["neg"].step.value})

    async def reset_failed(self, negotiation_id):
        row = self.s.negotiations.get(negotiation_id)
        if row is None or row["neg"].status != Status.FAILED:
            return False
        row["neg"].status, row["neg"].error = Status.PENDING, None
        return True


# --------------------------------------------------------------------------- postgres


class PostgresRepo(Repo):
    """psycopg 3 async. Use Neon's *pooled* connection string on Vercel."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None

    async def _c(self):
        if self._conn is None:
            import psycopg
            from psycopg.rows import dict_row

            self._conn = await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row, autocommit=True)
        return self._conn

    async def close(self):
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @staticmethod
    def _jsonb(value: Any):
        from psycopg.types.json import Jsonb

        return Jsonb(value)

    @staticmethod
    def _neg(row: Dict[str, Any]) -> Negotiation:
        return Negotiation(
            id=str(row["id"]),
            buyer_input=row["buyer_input"],
            brief=BuyerBrief.model_validate(row["brief"]) if row["brief"] else None,
            status=Status(row["status"]),
            step=Step(row["step"]),
            error=row["error"],
        )

    async def create_negotiation(self, buyer_input, brief=None):
        conn = await self._c()
        neg_id = str(uuid.uuid4())
        step = Step.PROPOSE if brief else Step.BRIEF
        async with conn.transaction():
            row = await (await conn.execute(
                "insert into negotiations (id, buyer_input, brief, step) values (%s, %s, %s, %s) returning *",
                (neg_id, buyer_input, self._jsonb(brief.model_dump()) if brief else None, step.value),
            )).fetchone()
            if brief:
                await conn.execute(
                    "insert into events (negotiation_id, type, payload) values (%s, 'brief', %s)",
                    (neg_id, self._jsonb(brief.model_dump())),
                )
        return self._neg(row)

    async def get_negotiation(self, negotiation_id):
        conn = await self._c()
        row = await (await conn.execute("select * from negotiations where id = %s", (negotiation_id,))).fetchone()
        return self._neg(row) if row else None

    async def acquire_lease(self, negotiation_id, owner, seconds):
        conn = await self._c()
        cur = await conn.execute(
            """update negotiations
                  set lease_owner = %s, lease_until = now() + make_interval(secs => %s),
                      status = 'running', updated_at = now()
                where id = %s and status in ('pending', 'running')
                  and (lease_until is null or lease_until < now() or lease_owner = %s)""",
            (owner, seconds, negotiation_id, owner),
        )
        return cur.rowcount == 1

    async def release_lease(self, negotiation_id, owner):
        conn = await self._c()
        await conn.execute(
            "update negotiations set lease_owner = null, lease_until = null where id = %s and lease_owner = %s",
            (negotiation_id, owner),
        )

    async def list_items(self):
        conn = await self._c()
        rows = await (await conn.execute("select sku, name, category, color, material, size, price, stock, image from items order by sku")).fetchall()
        return [Item.model_validate(r) for r in rows]

    async def list_bundles(self, negotiation_id, round=None):
        conn = await self._c()
        rows = await (await conn.execute(
            """select * from bundles where negotiation_id = %s and (%s::int is null or round = %s::int)
               order by round, created_at, id""",
            (negotiation_id, round, round),
        )).fetchall()
        return [Bundle(id=str(r["id"]), negotiation_id=str(r["negotiation_id"]), round=r["round"], name=r["name"],
                       skus=list(r["skus"]), price=r["price"], pitch=r["pitch"])
                for r in rows]

    async def list_judgments(self, negotiation_id, round=None):
        conn = await self._c()
        rows = await (await conn.execute(
            "select * from judgments where negotiation_id = %s and (%s::int is null or round = %s::int)",
            (negotiation_id, round, round),
        )).fetchall()
        return [Judgment(bundle_id=str(r["bundle_id"]), negotiation_id=str(r["negotiation_id"]), round=r["round"],
                         probability=r["probability"], reason=r["reason"], price_score=r["price_score"],
                         fit_score=r["fit_score"], style_score=r["style_score"],
                         decision=r["decision"]) for r in rows]

    async def list_item_heat(self, negotiation_id, round):
        conn = await self._c()
        rows = await (await conn.execute(
            "select * from item_heat where negotiation_id = %s and round = %s order by score desc, sku",
            (negotiation_id, round),
        )).fetchall()
        return [ItemHeat(sku=r["sku"], score=r["score"], label=HeatLabel(r["label"]),
                         bundle_count=r["bundle_count"]) for r in rows]

    async def get_analysis(self, negotiation_id, round):
        conn = await self._c()
        row = await (await conn.execute(
            "select payload from analyses where negotiation_id = %s and round = %s", (negotiation_id, round),
        )).fetchone()
        return RoundAnalysis.model_validate(row["payload"]) if row else None

    async def list_events(self, negotiation_id, after=0):
        conn = await self._c()
        rows = await (await conn.execute(
            "select * from events where negotiation_id = %s and id > %s order by id", (negotiation_id, after),
        )).fetchall()
        return [Event(id=r["id"], negotiation_id=str(r["negotiation_id"]), type=r["type"], payload=r["payload"],
                      ts=r["ts"]) for r in rows]

    async def commit_step(self, negotiation_id, owner, from_step, to_step, *, lease_seconds,
                          status=Status.RUNNING, brief=None, bundles=(), judgments=(),
                          heat_round=None, heat=(), analysis=None, events=()):
        conn = await self._c()
        async with conn.transaction():
            cur = await conn.execute(
                """update negotiations
                      set step = %s, status = %s, brief = coalesce(%s, brief),
                          lease_until = now() + make_interval(secs => %s), updated_at = now()
                    where id = %s and lease_owner = %s and step = %s""",
                (to_step.value, status.value, self._jsonb(brief.model_dump()) if brief else None,
                 lease_seconds, negotiation_id, owner, from_step.value),
            )
            if cur.rowcount != 1:
                return False
            async with conn.cursor() as c:
                if bundles:
                    await c.executemany(
                        """insert into bundles (id, negotiation_id, round, name, skus, price, pitch)
                           values (%s, %s, %s, %s, %s, %s, %s)""",
                        [(b.id, b.negotiation_id, b.round, b.name, b.skus, b.price, b.pitch)
                         for b in bundles],
                    )
                if judgments:
                    await c.executemany(
                        """insert into judgments (bundle_id, negotiation_id, round, probability, reason,
                                                  price_score, fit_score, style_score, decision)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(j.bundle_id, j.negotiation_id, j.round, j.probability, j.reason,
                          j.price_score, j.fit_score, j.style_score, j.decision) for j in judgments],
                    )
                if heat_round is not None and heat:
                    await c.executemany(
                        """insert into item_heat (negotiation_id, round, sku, score, label, bundle_count)
                           values (%s, %s, %s, %s, %s, %s)""",
                        [(negotiation_id, heat_round, h.sku, h.score, h.label.value, h.bundle_count)
                         for h in heat],
                    )
                if analysis is not None:
                    await c.execute(
                        "insert into analyses (negotiation_id, round, payload) values (%s, %s, %s)",
                        (negotiation_id, analysis.round, self._jsonb(analysis.model_dump(mode="json"))),
                    )
                if events:
                    await c.executemany(
                        "insert into events (negotiation_id, type, payload) values (%s, %s, %s)",
                        [(negotiation_id, t, self._jsonb(p)) for t, p in events],
                    )
        return True

    async def mark_failed(self, negotiation_id, owner, error):
        conn = await self._c()
        async with conn.transaction():
            row = await (await conn.execute(
                """update negotiations set status = 'failed', error = %s, lease_owner = null, lease_until = null,
                          updated_at = now()
                    where id = %s and lease_owner = %s returning step""",
                (error, negotiation_id, owner),
            )).fetchone()
            if row:
                await conn.execute(
                    "insert into events (negotiation_id, type, payload) values (%s, 'error', %s)",
                    (negotiation_id, self._jsonb({"message": error, "step": row["step"]})),
                )

    async def reset_failed(self, negotiation_id):
        conn = await self._c()
        cur = await conn.execute(
            "update negotiations set status = 'pending', error = null, updated_at = now() "
            "where id = %s and status = 'failed'",
            (negotiation_id,),
        )
        return cur.rowcount == 1


def load_seed_items() -> List[Item]:
    path = os.path.join(os.path.dirname(__file__), "seed_items.json")
    with open(path) as f:
        return [Item.model_validate(x) for x in json.load(f)]


def make_repo() -> Repo:
    """New repo per caller. Each one owns its own DB connection, so close() it when done."""
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return PostgresRepo(dsn)
    repo = MemoryRepo()
    if not repo.s.items:
        repo.seed_items(load_seed_items())
    return repo
