import json

import pytest
from fastapi.testclient import TestClient

import middleman.events as events_mod
from api.index import app
from tests.conftest import FakeAgents


@pytest.fixture
def client(repo, items, monkeypatch):
    monkeypatch.setattr(events_mod, "POLL_SECONDS", 0.01)
    app.state.make_repo = lambda: type(repo)(repo.s)
    app.state.agents = FakeAgents(items)
    yield TestClient(app)


def parse_sse(text):
    out = []
    for chunk in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if not line.startswith(":"))
        if "data" in lines:
            out.append(json.loads(lines["data"]))
    return out


def test_create_stream_snapshot_and_replay(client):
    r = client.post("/api/negotiations", json={"buyer_input": "streetwear, size M, under $400"})
    assert r.status_code == 201
    nid = r.json()["id"]

    with client.stream("GET", f"/api/negotiations/{nid}/stream") as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(s.read().decode())
    types = [e["type"] for e in events]
    assert types[0] == "brief" and types[-3:] == ["final_offer", "decision", "done"]

    snap = client.get(f"/api/negotiations/{nid}").json()
    assert snap["negotiation"]["status"] == "done"
    assert [r["round"] for r in snap["rounds"]] == [1]
    assert len(snap["rounds"][0]["bundles"]) == 5
    assert all(b["judgment"] for b in snap["rounds"][0]["bundles"])
    assert snap["rounds"][0]["analysis"]["main_issue"] == "style"
    assert snap["final_offer"]["skus"]
    assert snap["decision"]["decision"] == "accept"

    # Reconnect with Last-Event-ID: only newer events, then the stream ends (already done)
    with client.stream("GET", f"/api/negotiations/{nid}/stream",
                       headers={"Last-Event-ID": str(events[-4]["id"])}) as s:
        replay = parse_sse(s.read().decode())
    assert [e["type"] for e in replay] == ["final_offer", "decision", "done"]


def test_failed_run_can_be_retried(client, items):
    app.state.agents = FakeAgents(items, fail_on="final_bundle")
    nid = client.post("/api/negotiations", json={"buyer_input": "x"}).json()["id"]
    with client.stream("GET", f"/api/negotiations/{nid}/stream") as s:
        assert parse_sse(s.read().decode())[-1]["type"] == "error"

    assert client.post(f"/api/negotiations/{nid}/retry").json()["step"] == "FINAL"
    with client.stream("GET", f"/api/negotiations/{nid}/stream", params={"after": 10_000}) as s:
        assert [e["type"] for e in parse_sse(s.read().decode())] == []  # nothing newer than `after`
    assert client.get(f"/api/negotiations/{nid}").json()["negotiation"]["status"] == "done"
    assert client.post(f"/api/negotiations/{nid}/retry").status_code == 409


def test_unknown_ids_404(client):
    assert client.get("/api/negotiations/not-a-uuid").status_code == 404
    assert client.get("/api/negotiations/00000000-0000-0000-0000-000000000000/stream").status_code == 404
