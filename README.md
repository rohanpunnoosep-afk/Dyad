# brojans
Troylabs

## Middle man backend (FastAPI on Vercel)

Runs buyer agent ↔ seller agent through one round of 5 bundles:
`BRIEF → PROPOSE → JUDGE → ANALYZE → FINAL → DECIDE → DONE`. All message shapes are in
[json_formats.md](json_formats.md); prices are dollars, items are SKUs.

1. **PROPOSE**: the seller builds 5 bundles from eligible inventory (in stock, buyer's sizes, no avoided colors).
2. **JUDGE**: the buyer rates all 5 (probability + price/fit/style scores). Each SKU gets a heat score: the
   mean probability of the bundles containing it (hot ≥ 0.6, cold ≤ 0.3).
3. **ANALYZE**: the seller checks every item of every bundle rated below 0.5. The middle man computes the
   mean probability per category/color/material/size/style and marks a failing attribute `confirmed` only
   when the item-level verdicts and the averages agree.
4. **FINAL**: the seller makes 1 offer built from that analysis; cold and dropped SKUs are rejected.
5. **DECIDE**: the buyer accepts or rejects the final offer.

Every seller output is validated (SKUs, stock, sizes, avoided colors, "must include" notes, budget,
price band) and re-prompted once with the errors.

| Endpoint | |
|---|---|
| `POST /api/negotiations` `{buyer_input, brief?}` | create; `brief` is an optional pre-built buyer context; returns `{id, stream_url}` |
| `GET /api/negotiations/{id}/stream` | SSE: replays history, runs/resumes the negotiation, streams live (`?after=` / `Last-Event-ID`) |
| `GET /api/negotiations/{id}` | JSON snapshot: bundles, ratings, heat, analysis, final offer, decision |
| `POST /api/negotiations/{id}/retry` | re-arm a failed negotiation (resumes at the failed step) |

SSE event types: `brief`, `check`, `bundles_proposed`, `ratings`, `heat`, `analysis`, `final_offer`, `decision`, `done`, `error`.

### Setup
1. Vercel → Storage → add **Neon Postgres** (sets `DATABASE_URL`, use the pooled URL) and add `OPENAI_API_KEY` (see *API keys* below).
2. `DATABASE_URL=... python scripts/setup_db.py` (applies `db/schema.sql`, seeds `db/seed_items.json`). If the
   database still has the old cents/tags tables, the script stops and says which tables to drop.
3. `vercel deploy`.

Optional env: `OPENAI_MODEL` (default `gpt-5.4`), `OPENAI_REASONING_EFFORT` (default `medium`; set empty for non-reasoning models).

### Local dev
```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                        # fake agents, in-memory store
.venv/bin/uvicorn api.index:app --reload --env-file .env.local
curl -X POST localhost:8000/api/negotiations -H 'content-type: application/json' -d '{"buyer_input":"workwear, size M top, 32 bottom, 10 shoe, under $400, must include a jacket"}'
curl -N localhost:8000/api/negotiations/<id>/stream
```
Without `DATABASE_URL`, an in-memory store with the seed inventory is used. That's fine locally, but not on Vercel.

### API keys
Never commit keys. `.env` and `.env.local` are gitignored.

- **Local:** create `.env.local` in the repo root:
  ```
  OPENAI_API_KEY=sk-...
  # DATABASE_URL=postgres://...   (optional; omit to use the in-memory store)
  ```
  and run uvicorn with `--env-file .env.local` as shown above.
- **Vercel:** Project → Settings → Environment Variables → add `OPENAI_API_KEY` for Production
  (and Preview if you use preview deploys), or run `vercel env add OPENAI_API_KEY`. Redeploy after
  adding. Pull them locally with `vercel env pull .env.local`.
